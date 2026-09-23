"""Model-call proxy: participants talk to the hub, which holds provider keys.

A daemon sets ``ANTHROPIC_BASE_URL=https://hub/proxy/anthropic`` and
``ANTHROPIC_API_KEY=<its network token>``. The Anthropic SDK then sends
``POST /proxy/anthropic/v1/messages`` here with the token in ``x-api-key``.
The hub checks the token, reserves against that participant's cap and the
cluster cap, forwards the request verbatim with the real key, records the
usage from the response, and returns the response body and status unchanged.
No key ever leaves the server; revoking one participant is deleting one
owner.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from efferents.agents.budget import BudgetExhausted, BudgetTracker, CallUsage, cost_usd, estimate_call_cost_usd
from efferents.cluster.budget import coordinator
from efferents.cluster.config import ClusterConfig, is_frozen, write_event

UPSTREAM_DEFAULT = "https://api.anthropic.com"
PROXY_PREFIX = "/proxy/anthropic"
OPENAI_PROXY_PREFIX = "/proxy/openai"
MAX_PROXY_BODY = 8 * 1024 * 1024
_FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "content-type", "accept")
_AZURE_MODELS = frozenset({"gpt-4.1-nano", "gpt-5.6-luna", "gpt-5.6-sol"})
_OPENAI_MAX_BODY = 512_000  # bounded input with room for coding context
_OPENAI_MAX_OUTPUT = 32768


class ProxyError(Exception):
    def __init__(self, status: int, message: str, kind: str = "proxy_error"):
        super().__init__(message)
        self.status = status
        self.kind = kind

    def body(self) -> bytes:
        return json.dumps({"type": "error", "error": {"type": self.kind, "message": str(self)}}).encode()


def _estimate_input_tokens(request: dict) -> int:
    # Four characters per token is the SDK's own rough rule for reservations.
    text = json.dumps(request.get("system", "")) + json.dumps(request.get("messages", []))
    return max(1, len(text) // 4)


class ModelProxy:
    def __init__(self, cfg: ClusterConfig, *, upstream: str | None = None, opener=None):
        self.cfg = cfg
        self.paths = cfg.paths
        self.upstream = (upstream or os.environ.get("EFFERENTS_PROXY_UPSTREAM") or UPSTREAM_DEFAULT).rstrip("/")
        self._open = opener or urllib.request.urlopen
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._pending_owner: dict[str, float] = {}
        self._pending_total = 0.0

    # --- ledgers -----------------------------------------------------------------

    def ledger_dir(self, owner_id: str) -> Path:
        d = self.paths.root / "proxy" / owner_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def tracker(self, owner_id: str) -> BudgetTracker:
        cap = float(self.cfg.proxy.cap_per_owner_usd)
        return BudgetTracker(self.ledger_dir(owner_id) / "budget.jsonl", daily_cap_usd=cap, total_cap_usd=cap)

    def cluster_tracker(self) -> BudgetTracker:
        cap = float(self.cfg.proxy.cap_total_usd)
        path = self.paths.root / "proxy" / "budget.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return BudgetTracker(path, daily_cap_usd=cap, total_cap_usd=cap)

    def spend(self, owner_id: str) -> float:
        return self.tracker(owner_id).spend_total()

    def _lock(self, owner_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(owner_id, threading.Lock())

    # --- the call ----------------------------------------------------------------

    def forward(self, *, owner_id: str, path: str, body: bytes, headers: dict[str, str],
                api_key: str, provider: str = "anthropic") -> tuple[int, bytes, dict[str, str]]:
        """Forward one SDK request. Returns (status, body, headers) for the client."""
        if provider == "openai" and path not in ("/v1/chat/completions", "/v1/responses"):
            raise ProxyError(404, "unknown proxy path", "not_found_error")
        if provider != "openai" and (provider != "anthropic" or not path.startswith("/v1/")):
            raise ProxyError(404, "unknown proxy path", "not_found_error")
        if is_frozen(self.paths):
            raise ProxyError(402, "the event budget is frozen", "budget_frozen")
        try:
            request = json.loads(body.decode("utf-8")) if body else {}
        except ValueError as e:
            raise ProxyError(400, f"request body is not JSON: {e}", "invalid_request_error") from e
        if not isinstance(request, dict):
            raise ProxyError(400, "request body must be an object", "invalid_request_error")
        responses_api = provider == "openai" and path == "/v1/responses"
        if request.get("stream") and not responses_api:
            raise ProxyError(400, "streaming is not supported through the event proxy",
                             "invalid_request_error")
        model = str(request.get("model") or "")
        if provider == "openai":
            if len(body) > _OPENAI_MAX_BODY:
                raise ProxyError(413, "model request exceeds the event text limit", "invalid_request_error")
            if model not in _AZURE_MODELS:
                raise ProxyError(400, "model is not an approved event deployment", "invalid_request_error")
            if request.get("n", 1) != 1 or request.get("best_of", 1) != 1:
                raise ProxyError(400, "multiple completions are not supported", "invalid_request_error")
            if responses_api:
                if not isinstance(request.get("input"), (str, list)):
                    raise ProxyError(400, "input must be text or an array", "invalid_request_error")
                request.setdefault("max_output_tokens", _OPENAI_MAX_OUTPUT)
                if model == "gpt-5.6-sol":
                    request.setdefault("reasoning", {"effort": "high"})
            elif request.get("messages") is None or not isinstance(request["messages"], list):
                raise ProxyError(400, "messages must be an array", "invalid_request_error")
            if any(term in body.lower() for term in (b'"image_url"', b'"input_audio"', b'"file_id"')):
                raise ProxyError(400, "only text and function tools are supported", "invalid_request_error")
            if model.startswith("gpt-5.6-") and not responses_api:
                if any(field in request for field in ("temperature", "top_p", "logprobs")):
                    raise ProxyError(400, "sampling options are unsupported for GPT-5.6", "invalid_request_error")
                request["max_completion_tokens"] = request.pop("max_completion_tokens", request.pop("max_tokens", 0))
                request["reasoning_effort"] = "none" if request.get("tools") else "high"
            max_tokens = (request.get("max_output_tokens") if responses_api else
                          request.get("max_completion_tokens") or request.get("max_tokens"))
            if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= _OPENAI_MAX_OUTPUT:
                raise ProxyError(400, "max output tokens must be 1–32768", "invalid_request_error")
            model = f"openai/{model}"
            body = json.dumps(request).encode("utf-8")
        else:
            max_tokens = request.get("max_tokens")
            if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= _OPENAI_MAX_OUTPUT:
                raise ProxyError(400, "max output tokens must be 1–32768", "invalid_request_error")
        est_in = max(1, len(body) // 3) if provider == "openai" else _estimate_input_tokens(request)
        if provider == "openai":
            upstream = os.environ.get("EFFERENTS_AZURE_OPENAI_ENDPOINT", "").rstrip("/")
            if not upstream.startswith("https://") or not upstream.endswith("/openai/v1"):
                raise ProxyError(503, "Azure OpenAI endpoint is not configured", "api_error")
            out_headers = {"content-type": "application/json", "api-key": api_key}
            upstream_path = "/responses" if responses_api else "/chat/completions"
        else:
            upstream = self.upstream
            out_headers = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
            out_headers.setdefault("content-type", "application/json")
            out_headers.setdefault("anthropic-version", "2023-06-01")
            out_headers["x-api-key"] = api_key
            upstream_path = path
        owner_tracker = self.tracker(owner_id)
        cluster_tracker = self.cluster_tracker()
        estimate = estimate_call_cost_usd(model, max_tokens, est_in)
        if estimate <= 0:
            raise ProxyError(400, "Model pricing is unavailable; this request cannot be budgeted.",
                             "invalid_request_error")
        with self._guard:
            try:
                owner_tracker.reserve(model, max_tokens, est_in)
                cluster_tracker.reserve(model, max_tokens, est_in)
                owner_pending = self._pending_owner.get(owner_id, 0.0)
                owner_spend = owner_tracker.spend_total()
                cluster_spend = cluster_tracker.spend_total()
                if owner_spend + owner_pending + estimate > owner_tracker.total_cap:
                    raise BudgetExhausted("total", spend=owner_spend + owner_pending,
                                          cap=owner_tracker.total_cap, estimate=estimate)
                if cluster_spend + self._pending_total + estimate > cluster_tracker.total_cap:
                    raise BudgetExhausted("total", spend=cluster_spend + self._pending_total,
                                          cap=cluster_tracker.total_cap, estimate=estimate)
            except BudgetExhausted as e:
                write_event(self.paths, "proxy_cap", owner_id=owner_id, scope=e.scope,
                            spend=round(e.spend, 4), cap=e.cap)
                raise ProxyError(
                    402, f"your event model budget is used up ({e.scope} cap ${e.cap:.2f})",
                    "budget_exhausted",
                ) from e
            try:
                reservation = coordinator(self.cfg).reserve(owner_id, estimate, family="proxy")
            except BudgetExhausted as e:
                raise ProxyError(402, f"Your shared event allocation is used up ({e.scope} cap ${e.cap:.2f}).",
                                 "budget_exhausted") from e
            self._pending_owner[owner_id] = self._pending_owner.get(owner_id, 0.0) + estimate
            self._pending_total += estimate
        req = urllib.request.Request(upstream + upstream_path, data=body, headers=out_headers, method="POST")
        settled = False
        try:
            try:
                with self._open(req, timeout=600) as resp:
                    status = resp.status
                    payload = resp.read()
                    resp_headers = {"content-type": resp.headers.get("Content-Type", "application/json")}
            except urllib.error.HTTPError as e:
                payload = e.read()
                status = e.code
                resp_headers = {"content-type": e.headers.get("Content-Type", "application/json")}
                retry_after = e.headers.get("retry-after")
                if retry_after:
                    resp_headers["retry-after"] = retry_after
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                raise ProxyError(502, f"upstream unreachable: {e}", "api_error") from e
            if 200 <= status < 300:
                self._record(owner_id, model, payload, owner_tracker, cluster_tracker,
                             provider=provider, fallback_input=est_in,
                             fallback_output=max_tokens, responses_api=responses_api,
                             streaming=bool(request.get("stream")), reservation_id=reservation)
            settled = True
            return status, payload, resp_headers
        finally:
            # A transport failure can happen after the provider accepted a paid
            # request. Keep the hold until its billing can be inspected.
            if settled:
                coordinator(self.cfg).release(reservation)
            with self._guard:
                self._pending_owner[owner_id] -= estimate
                self._pending_total -= estimate

    def _record(self, owner_id: str, model: str, payload: bytes, owner_tracker: BudgetTracker,
                cluster_tracker: BudgetTracker, *, provider: str = "anthropic",
                fallback_input: int = 0, fallback_output: int = 0,
                responses_api: bool = False, streaming: bool = False,
                reservation_id: str | None = None) -> None:
        if responses_api and streaming:
            completed = None
            for line in payload.splitlines():
                if not line.startswith(b"data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                if event.get("type") == "response.completed":
                    completed = event.get("response")
            payload = json.dumps(completed or {}).encode()
        try:
            data = json.loads(payload.decode("utf-8"))
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        usage_raw = data.get("usage") or {}
        if not isinstance(usage_raw, dict):
            usage_raw = {}
        if not usage_raw:
            # A successful response without usage must not become a free call.
            usage_raw = {("input_tokens" if responses_api or provider != "openai" else "prompt_tokens"): fallback_input,
                         ("output_tokens" if responses_api or provider != "openai" else "completion_tokens"): fallback_output}
        cached = 0
        if responses_api:
            cached = int((usage_raw.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0)
        input_tokens = int(usage_raw.get("input_tokens" if responses_api or provider != "openai" else "prompt_tokens", 0) or 0)
        usage = CallUsage(
            input_tokens=max(0, input_tokens - cached),
            output_tokens=int(usage_raw.get("output_tokens" if responses_api or provider != "openai" else "completion_tokens", 0) or 0),
            cache_creation_input_tokens=int(usage_raw.get("cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=cached or int(usage_raw.get("cache_read_input_tokens", 0) or 0),
        )
        served = model if provider == "openai" else str(data.get("model") or model)
        if cost_usd(served, CallUsage(1, 1)) <= 0:
            served = model
        with self._lock(owner_id):
            owner_tracker.record(agent="proxy", model=served, usage=usage, notes=f"owner={owner_id} reservation={reservation_id or 'none'}")
            cluster_tracker.record(agent="proxy", model=served, usage=usage, notes=f"owner={owner_id} reservation={reservation_id or 'none'}")


def proxy_spend_total(paths) -> float:
    path = Path(paths.root) / "proxy" / "budget.jsonl"
    if not path.is_file():
        return 0.0
    total = 0.0
    for line in path.read_text().splitlines():
        try:
            total += float(json.loads(line).get("cost_usd", 0.0) or 0.0)
        except (ValueError, TypeError):
            continue
    return total


__all__ = ["ModelProxy", "ProxyError", "PROXY_PREFIX", "OPENAI_PROXY_PREFIX", "MAX_PROXY_BODY", "proxy_spend_total",
           "estimate_call_cost_usd"]

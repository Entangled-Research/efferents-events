"""Model-call proxy: participants' daemons talk to the hub, the hub talks to
Anthropic with the organizer's key.

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

from efferents.agents.budget import BudgetExhausted, BudgetTracker, CallUsage, estimate_call_cost_usd
from efferents.cluster.config import ClusterConfig, is_frozen, write_event

UPSTREAM_DEFAULT = "https://api.anthropic.com"
PROXY_PREFIX = "/proxy/anthropic"
MAX_PROXY_BODY = 8 * 1024 * 1024
_FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "content-type", "accept")


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
                api_key: str) -> tuple[int, bytes, dict[str, str]]:
        """Forward one SDK request. Returns (status, body, headers) for the client."""
        if not path.startswith("/v1/"):
            raise ProxyError(404, "unknown proxy path", "not_found_error")
        if is_frozen(self.paths):
            raise ProxyError(402, "the event budget is frozen", "budget_frozen")
        try:
            request = json.loads(body.decode("utf-8")) if body else {}
        except ValueError as e:
            raise ProxyError(400, f"request body is not JSON: {e}", "invalid_request_error") from e
        if not isinstance(request, dict):
            raise ProxyError(400, "request body must be an object", "invalid_request_error")
        if request.get("stream"):
            raise ProxyError(400, "streaming is not supported through the event proxy",
                             "invalid_request_error")
        model = str(request.get("model") or "")
        max_tokens = int(request.get("max_tokens") or 0)
        est_in = _estimate_input_tokens(request)
        owner_tracker = self.tracker(owner_id)
        cluster_tracker = self.cluster_tracker()
        with self._lock(owner_id):
            try:
                owner_tracker.reserve(model, max_tokens, est_in)
                cluster_tracker.reserve(model, max_tokens, est_in)
            except BudgetExhausted as e:
                write_event(self.paths, "proxy_cap", owner_id=owner_id, scope=e.scope,
                            spend=round(e.spend, 4), cap=e.cap)
                raise ProxyError(
                    402, f"your event model budget is used up ({e.scope} cap ${e.cap:.2f})",
                    "budget_exhausted",
                ) from e
        out_headers = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
        out_headers.setdefault("content-type", "application/json")
        out_headers.setdefault("anthropic-version", "2023-06-01")
        out_headers["x-api-key"] = api_key
        req = urllib.request.Request(self.upstream + path, data=body, headers=out_headers, method="POST")
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
            self._record(owner_id, model, payload, owner_tracker, cluster_tracker)
        return status, payload, resp_headers

    def _record(self, owner_id: str, model: str, payload: bytes, owner_tracker: BudgetTracker,
                cluster_tracker: BudgetTracker) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except ValueError:
            return
        usage_raw = data.get("usage") or {}
        usage = CallUsage(
            input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
            cache_creation_input_tokens=int(usage_raw.get("cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=int(usage_raw.get("cache_read_input_tokens", 0) or 0),
        )
        served = str(data.get("model") or model)
        with self._lock(owner_id):
            owner_tracker.record(agent="proxy", model=served, usage=usage, notes=f"owner={owner_id}")
            cluster_tracker.record(agent="proxy", model=served, usage=usage, notes=f"owner={owner_id}")


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


__all__ = ["ModelProxy", "ProxyError", "PROXY_PREFIX", "MAX_PROXY_BODY", "proxy_spend_total",
           "estimate_call_cost_usd"]

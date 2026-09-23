from __future__ import annotations

import io
import json
import threading
import urllib.error
from email.message import Message

import pytest

from efferents.cluster.config import set_control_flag
from efferents.cluster.proxy import ModelProxy, ProxyError
from tests.cluster_helpers import make_cluster


class FakeResponse(io.BytesIO):
    def __init__(self, payload: dict, status: int = 200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_response(model="claude-sonnet-4-6", in_tok=1000, out_tok=100):
    return {"id": "msg", "type": "message", "model": model, "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok}}


def _request(model="claude-sonnet-4-6", max_tokens=200):
    return json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": "hello"}]}).encode()


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 0.05, "cap_total_usd": 0.08})
    seen = []

    def opener(req, timeout=0):
        seen.append(req)
        return FakeResponse(_ok_response())

    return ModelProxy(cfg, upstream="https://upstream.test", opener=opener), seen, cfg


def test_forward_records_usage_and_hides_key(proxy):
    px, seen, cfg = proxy
    status, body, headers = px.forward(owner_id="o1", path="/v1/messages", body=_request(),
                                       headers={"x-api-key": "participant-token",
                                                "anthropic-version": "2023-06-01",
                                                "cookie": "secret=1"},
                                       api_key="sk-real")
    assert status == 200 and json.loads(body)["usage"]["input_tokens"] == 1000
    req = seen[0]
    assert req.full_url == "https://upstream.test/v1/messages"
    assert req.get_header("X-api-key") == "sk-real"
    assert req.get_header("Cookie") is None
    assert px.spend("o1") > 0
    assert (cfg.paths.root / "proxy" / "budget.jsonl").exists()


def test_owner_and_cluster_caps(proxy):
    px, seen, cfg = proxy
    # Each Sonnet call costs ~ $0.0045; the owner cap of $0.05 allows a few,
    # then refuses with 402 before contacting upstream.
    n = 0
    while n < 50:
        try:
            px.forward(owner_id="o1", path="/v1/messages", body=_request(), headers={}, api_key="k")
            n += 1
        except ProxyError as exc:
            assert exc.status == 402 and exc.kind == "budget_exhausted"
            break
    else:
        pytest.fail("cap never bound")
    calls_before = len(seen)
    with pytest.raises(ProxyError):
        px.forward(owner_id="o1", path="/v1/messages", body=_request(), headers={}, api_key="k")
    assert len(seen) == calls_before  # refused before upstream
    # A second owner is limited by the cluster cap ($0.08 total).
    with pytest.raises(ProxyError) as exc:
        for _ in range(50):
            px.forward(owner_id="o2", path="/v1/messages", body=_request(), headers={}, api_key="k")
    assert "cap" in str(exc.value)


def test_frozen_streaming_and_bad_paths(proxy):
    px, seen, cfg = proxy
    with pytest.raises(ProxyError) as exc:
        px.forward(owner_id="o1", path="/v1/messages",
                   body=json.dumps({"model": "m", "max_tokens": 1, "stream": True, "messages": []}).encode(),
                   headers={}, api_key="k")
    assert exc.value.status == 400
    with pytest.raises(ProxyError) as exc:
        px.forward(owner_id="o1", path="/other", body=_request(), headers={}, api_key="k")
    assert exc.value.status == 404
    set_control_flag(cfg.paths, "frozen", "test")
    with pytest.raises(ProxyError) as exc:
        px.forward(owner_id="o1", path="/v1/messages", body=_request(), headers={}, api_key="k")
    assert exc.value.status == 402 and exc.value.kind == "budget_frozen"


def test_upstream_errors_pass_through_without_charging(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)

    def opener(req, timeout=0):
        hdrs = Message()
        hdrs["Content-Type"] = "application/json"
        hdrs["retry-after"] = "7"
        raise urllib.error.HTTPError(req.full_url, 429, "rate limited", hdrs,
                                     io.BytesIO(b'{"type":"error","error":{"type":"rate_limit_error"}}'))

    px = ModelProxy(cfg, upstream="https://upstream.test", opener=opener)
    status, body, headers = px.forward(owner_id="o1", path="/v1/messages", body=_request(),
                                       headers={}, api_key="k")
    assert status == 429 and b"rate_limit_error" in body and headers["retry-after"] == "7"
    assert px.spend("o1") == 0.0


def test_azure_openai_proxy_routes_and_prices(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 0.05,
                                                   "cap_total_usd": 0.08})
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    seen = []

    def opener(req, timeout=0):
        seen.append(req)
        return FakeResponse({"model": "gpt-5.6-luna", "choices": [],
                             "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})

    px = ModelProxy(cfg, opener=opener)
    request = json.dumps({"model": "gpt-5.6-luna", "max_tokens": 200,
                          "messages": [{"role": "user", "content": "hello"}],
                          "tools": [{"type": "function", "function": {"name": "do_it"}}]}).encode()
    status, _, _ = px.forward(owner_id="o1", path="/v1/chat/completions", body=request,
                              headers={"authorization": "Bearer participant", "cookie": "secret"},
                              api_key="azure-secret", provider="openai")
    assert status == 200
    assert seen[0].full_url == "https://resource.openai.azure.com/openai/v1/chat/completions"
    assert seen[0].get_header("Api-key") == "azure-secret"
    assert seen[0].get_header("Authorization") is None
    assert seen[0].get_header("Cookie") is None
    sent = json.loads(seen[0].data)
    assert sent["max_completion_tokens"] == 200 and "max_tokens" not in sent
    assert sent["reasoning_effort"] == "none"
    assert px.spend("o1") > 0
    assert json.loads((cfg.paths.root / "proxy" / "o1" / "budget.jsonl").read_text().splitlines()[0])["model"] == "openai/gpt-5.6-luna"


def test_azure_openai_proxy_rejects_unpriced_or_unbounded_calls(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    seen = []
    px = ModelProxy(cfg, opener=lambda req, timeout=0: seen.append(req))
    base = {"model": "gpt-5.6-sol", "max_tokens": 100,
            "messages": [{"role": "user", "content": "hello"}]}
    for changed in ({"model": "gpt-4o"}, {"stream": True}, {"n": 2},
                    {"max_tokens": 32769}, {"temperature": 0.5}):
        with pytest.raises(ProxyError) as exc:
            px.forward(owner_id="o1", path="/v1/chat/completions",
                       body=json.dumps({**base, **changed}).encode(), headers={},
                       api_key="azure-secret", provider="openai")
        assert exc.value.status == 400
    assert not seen


def test_pending_calls_count_against_shared_cap(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 0.01,
                                                   "cap_total_usd": 0.015})
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    entered, release = threading.Event(), threading.Event()

    def opener(req, timeout=0):
        entered.set()
        assert release.wait(5)
        return FakeResponse({"model": "gpt-5.6-sol", "choices": [],
                             "usage": {"prompt_tokens": 100, "completion_tokens": 100}})

    px = ModelProxy(cfg, opener=opener)
    body = json.dumps({"model": "gpt-5.6-sol", "max_tokens": 300,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    done = []
    thread = threading.Thread(target=lambda: done.append(px.forward(
        owner_id="o1", path="/v1/chat/completions", body=body, headers={},
        api_key="key", provider="openai")))
    thread.start()
    assert entered.wait(5)
    with pytest.raises(ProxyError) as exc:
        px.forward(owner_id="o2", path="/v1/chat/completions", body=body,
                   headers={}, api_key="key", provider="openai")
    assert exc.value.status == 402
    release.set()
    thread.join(5)
    assert not thread.is_alive() and done[0][0] == 200


def test_azure_success_without_usage_is_charged_conservatively(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    px = ModelProxy(cfg, opener=lambda req, timeout=0: FakeResponse({"choices": []}))
    body = json.dumps({"model": "gpt-4.1-nano", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    px.forward(owner_id="o1", path="/v1/chat/completions", body=body,
               headers={}, api_key="key", provider="openai")
    assert px.spend("o1") > 0


def test_uncertain_transport_failure_keeps_durable_budget_hold(tmp_path, monkeypatch):
    from efferents.cluster.budget import SpendCoordinator
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT", "https://resource.openai.azure.com/openai/v1")
    def lost_response(req, timeout=0):
        raise TimeoutError("response lost after request")
    px = ModelProxy(cfg, opener=lost_response)
    body = json.dumps({"model": "gpt-4.1-nano", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    with pytest.raises(ProxyError) as caught:
        px.forward(owner_id="o1", path="/v1/chat/completions", body=body,
                   headers={}, api_key="key", provider="openai")
    assert caught.value.status == 502
    holds = SpendCoordinator(cfg).reservations("o1")
    assert len(holds) == 1 and holds[0]["held_usd"] > 0
    assert px.spend("o1") == 0


def test_confirmed_proxy_error_releases_durable_hold(tmp_path, monkeypatch):
    from efferents.cluster.budget import SpendCoordinator
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT", "https://resource.openai.azure.com/openai/v1")
    px = ModelProxy(cfg, opener=lambda req, timeout=0: FakeResponse({"error": "rate limited"}, status=429))
    body = json.dumps({"model": "gpt-4.1-nano", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    status, _, _ = px.forward(owner_id="o1", path="/v1/chat/completions", body=body,
                              headers={}, api_key="key", provider="openai")
    assert status == 429
    assert SpendCoordinator(cfg).reservations("o1") == []
    assert px.spend("o1") == 0


def test_anthropic_cannot_bypass_allocation_with_unbounded_or_unpriced_calls(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    calls = []
    px = ModelProxy(cfg, opener=lambda req, timeout=0: calls.append(req))
    for max_tokens in (-100, 0, True, "100", 32769):
        with pytest.raises(ProxyError) as caught:
            px.forward(owner_id="o1", path="/v1/messages", body=_request(max_tokens=max_tokens),
                       headers={}, api_key="key")
        assert caught.value.status == 400
    with pytest.raises(ProxyError):
        px.forward(owner_id="o1", path="/v1/messages", body=_request(model="unpriced-imaginary-model"),
                   headers={}, api_key="key")
    assert calls == []


def test_anthropic_missing_usage_still_settles_conservative_charge(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    px = ModelProxy(cfg, opener=lambda req, timeout=0: FakeResponse({"model": "unknown-model", "content": []}))
    px.forward(owner_id="o1", path="/v1/messages", body=_request(), headers={}, api_key="key")
    assert px.spend("o1") > 0


def test_organizer_pause_blocks_proxy_before_any_provider_call(tmp_path, monkeypatch):
    from efferents.cluster.budget import SpendCoordinator
    cfg = make_cluster(tmp_path, monkeypatch)
    calls = []
    px = ModelProxy(cfg, opener=lambda req, timeout=0: calls.append(req))
    set_control_flag(cfg.paths, "pause_all", "Organizer paused the event")
    with pytest.raises(ProxyError) as caught:
        px.forward(owner_id="o1", path="/v1/messages", body=_request(), headers={}, api_key="key")
    assert caught.value.status == 402 and caught.value.kind == "event_paused"
    assert not calls and SpendCoordinator(cfg).reservations() == []

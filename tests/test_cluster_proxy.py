from __future__ import annotations

import io
import json
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

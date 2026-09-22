"""The terminal path over HTTP: intake.md, config, tracks, register, heartbeat,
journal push, feed, reviews, bind, proxy, and remote labs in the portfolio."""
from __future__ import annotations

import io
import json
import tarfile
import threading
from email.message import Message

import pytest

from efferents.cluster.config import set_control_flag
from efferents.cluster.context import ClusterContext
from efferents.cluster.server import make_cluster_server
from efferents.cluster.tracks import load_tracks
from tests.cluster_helpers import VALID_HYP, ScriptedClient, make_cluster, make_popper_repo
from tests.test_cluster_server import _join, _request


@pytest.fixture
def hub(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch, labs={"auto_start": False, "max_per_owner": 1})
    scripts: dict = {"replies": []}
    ctx = ClusterContext(cfg, tracks=load_tracks(cfg.tracks_path),
                         client_factory=lambda budget: ScriptedClient(scripts["replies"], budget=budget))
    upstream_calls = []

    class FakeResp(io.BytesIO):
        status = 200

        def __init__(self, *, openai=False):
            usage = ({"prompt_tokens": 10, "completion_tokens": 5} if openai else
                     {"input_tokens": 10, "output_tokens": 5})
            super().__init__(json.dumps({"model": "gpt-4.1-nano" if openai else "claude-sonnet-4-6",
                                         "content": [], "usage": usage}).encode())
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        upstream_calls.append(req)
        return FakeResp(openai="/openai/v1/" in req.full_url)

    ctx.proxy._open = opener
    httpd, ctx = make_cluster_server(cfg, port=0, context=ctx, read_ttl_s=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield port, ctx, scripts, cfg, upstream_calls
    httpd.shutdown()
    httpd.server_close()


def _bearer(body):
    return {"Authorization": f"Bearer {body['cluster']['network_token']}"}


def test_intake_md_and_config(hub):
    port, ctx, scripts, cfg, _ = hub
    status, body, headers = _request(port, "/intake.md")
    assert status == 200 and "Launch an efferents research lab" in body["raw"]
    assert f"Hub: http://127.0.0.1:{port}" in body["raw"]
    joined, hdrs = _join(port, "Ada")
    assert joined["cluster"]["network_token"] == joined["owner_link"].split("=")[1]
    status, config, _ = _request(port, "/api/network/config", headers=_bearer(joined))
    assert status == 200
    assert config["env"]["ANTHROPIC_BASE_URL"].endswith("/proxy/anthropic")
    assert config["env"]["EFFERENTS_NETWORK_TOKEN"] == joined["cluster"]["network_token"]
    assert config["lab_yaml"]["cadence"]["runs_per_digest"] == 3
    assert config["tracks"][0]["id"] == "coefficient-sweep"
    assert "efferents-events" in config["install"]["pip_spec"]
    # Without a token the machine endpoints are closed.
    assert _request(port, "/api/network/config")[0] == 401


def test_track_tarball(hub):
    port, *_ = hub
    joined, _ = _join(port, "Ada")
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/api/network/tracks/coefficient-sweep.tar.gz", headers=_bearer(joined))
    resp = conn.getresponse()
    data = resp.read()
    assert resp.status == 200 and resp.getheader("Content-Type") == "application/gzip"
    names = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz").getnames()
    assert "coefficient-sweep/track.yaml" in names
    assert "coefficient-sweep/submission/lab.yaml" in names
    assert "coefficient-sweep/submission/src/stub_run.py" in names
    assert not any("hypothesis.md" in n for n in names)
    assert _request(port, "/api/network/tracks/nope.tar.gz", headers=_bearer(joined))[0] == 404


def test_register_heartbeat_push_pull_and_portfolio(hub):
    port, ctx, scripts, cfg, upstream = hub
    ada, ada_hdrs = _join(port, "Ada")
    bob, bob_hdrs = _join(port, "Bob")
    A, B = _bearer(ada), _bearer(bob)
    reg = {"lab_id": "ada-lab", "domain": "synthetic", "hypothesis": VALID_HYP,
           "track": "coefficient-sweep", "host": "adas-macbook"}
    status, body, _ = _request(port, "/api/network/labs", method="POST", payload=reg, headers=A)
    assert status == 200 and body["registered"] and body["heartbeat_s"] == 30.0
    # Same id by another owner is refused; owner limit is enforced.
    assert _request(port, "/api/network/labs", method="POST", payload=reg, headers=B)[0] == 409
    assert _request(port, "/api/network/labs", method="POST",
                    payload={**reg, "lab_id": "ada-second"}, headers=A)[0] == 409
    assert _request(port, "/api/network/labs", method="POST",
                    payload={**reg, "hypothesis": "---\nfalsifiability_gate: failed\n---\n"},
                    headers=B)[0] == 422
    # Re-registering your own lab renews it.
    assert _request(port, "/api/network/labs", method="POST", payload=reg, headers=A)[0] == 200

    beat = {"status": "running", "runs": 7, "spend_usd": 0.42, "cap_usd": 3.0,
            "headline": {"column": "synthetic_loss", "direction": "min", "best": 0.09,
                         "latest": 0.1, "observations": 7},
            "hypothesis": {"question": "Does it?", "claim": "yes", "falsifier": "no", "student": "primary"},
            "verdict": {"status": "survives", "line": "verdict: survives"}, "papers": 1,
            "ideas": [{"name": "Bounded search"}],
            "review_board": {"status": "rejected", "scores": {"critical": 2, "neutral": 4, "optimistic": 6}},
            "edges": {"cited": [{"target": "bob-lab", "campaign_id": "c9"}]}}
    status, reply, _ = _request(port, "/api/network/labs/ada-lab/heartbeat", method="POST",
                                payload=beat, headers=A)
    assert status == 200 and reply["pause"] is False
    assert _request(port, "/api/network/labs/ada-lab/heartbeat", method="POST",
                    payload=beat, headers=B)[0] == 403

    # Everyone joined sees the remote lab in the portfolio and its views.
    status, portfolio, _ = _request(port, "/api/labs", headers=bob_hdrs)
    rows = {r["lab_id"]: r for r in portfolio["labs"]}
    assert rows["ada-lab"]["remote"] is True and rows["ada-lab"]["owner_name"] == "Ada"
    assert rows["ada-lab"]["ideas"] == beat["ideas"]
    assert rows["ada-lab"]["review_board"] == beat["review_board"]
    assert rows["ada-lab"]["status"] == "running" and rows["ada-lab"]["headline"]["best"] == 0.09
    status, state, _ = _request(port, "/api/labs/ada-lab/state", headers=bob_hdrs)
    assert status == 200 and state["budget"]["spent"] == 0.42
    status, control, _ = _request(port, "/api/labs/ada-lab/control", headers=ada_hdrs)
    assert control["remote"] is True and control["owner_name"] == "Ada"
    status, body, _ = _request(port, "/api/labs/ada-lab/steer", method="POST",
                               payload={"message": "x"}, headers=ada_hdrs)
    assert status == 409 and "own" in body["error"]

    # Journal push lands in the hub and, after a sync, in the feed.
    journal = ("# Journal\n\n<!-- ENTRIES BELOW -->\n\n## 2026-09-20 14:00 UTC — c1\n"
               "**Lab**: ada-lab\n**Headline**: Loss fell under 0.1\n")
    status, pushed, _ = _request(port, "/api/network/labs/ada-lab/journal", method="POST",
                                 payload={"journal": journal, "papers": {"c1": "# paper c1\n"}}, headers=A)
    assert pushed["entries_added"] == 1 and pushed["papers_stored"] == 1
    status, pushed, _ = _request(port, "/api/network/labs/ada-lab/journal", method="POST",
                                 payload={"journal": journal}, headers=A)
    assert pushed["entries_added"] == 0
    from efferents.cluster import sync
    summary = sync.sync_once(cfg, reviews=False)
    assert summary["new_entries"] == 1
    status, feed, _ = _request(port, "/api/network/feed", headers=B)
    assert "Loss fell under 0.1" in feed["raw"]
    status, papers, _ = _request(port, "/api/labs/ada-lab/papers", headers=bob_hdrs)
    assert status == 200
    status, activity, _ = _request(port, "/api/labs/ada-lab/activity", headers=bob_hdrs)
    assert activity[0]["title"].endswith("c1")

    # Reviews written for the lab are pulled by its owner only.
    (cfg.paths.root / "network" / "labs" / "ada-lab" / "paper" / "incoming_reviews.md").write_text("# r\n")
    assert _request(port, "/api/network/labs/ada-lab/reviews", headers=A)[1]["raw"] == "# r\n"
    assert _request(port, "/api/network/labs/ada-lab/reviews", headers=B)[0] == 403

    # A cluster-wide pause reaches the laptop through the next heartbeat.
    set_control_flag(cfg.paths, "pause_all", "test")
    status, reply, _ = _request(port, "/api/network/labs/ada-lab/heartbeat", method="POST",
                                payload=beat, headers=A)
    assert reply["pause"] is True and "paused" in reply["message"]

    # Edges reported in the heartbeat show on the map once the target exists.
    _request(port, "/api/network/labs", method="POST",
             payload={**reg, "lab_id": "bob-lab", "host": "bobs-pc"}, headers=B)
    status, portfolio, _ = _request(port, "/api/labs", headers=bob_hdrs)
    assert {(e["kind"], e["source"], e["target"]) for e in portfolio["edges"]} >= {("cited", "ada-lab", "bob-lab")}


def test_bind_and_proxy(hub):
    port, ctx, scripts, cfg, upstream = hub
    ada, _ = _join(port, "Ada")
    A = _bearer(ada)
    scripts["replies"].append(json.dumps({
        "falsifiers": [{"id": "F1", "description": "Median loss stays >= 0.1",
                        "when": {"column": "synthetic_loss", "agg": "median", "op": ">=", "value": 0.1}}],
        "rationale": "r", "lab_id": "x"}))
    status, binding, _ = _request(port, "/api/network/bind", method="POST",
                                  payload={"track_id": "coefficient-sweep", "hypothesis": VALID_HYP},
                                  headers=A)
    assert status == 200 and binding["validated"] and binding["rules_text"]

    import http.client
    body = json.dumps({"model": "claude-sonnet-4-6", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/proxy/anthropic/v1/messages", body=body,
                 headers={"Content-Type": "application/json", "x-api-key": ada["cluster"]["network_token"],
                          "anthropic-version": "2023-06-01"})
    resp = conn.getresponse()
    payload = json.loads(resp.read())
    assert resp.status == 200 and payload["usage"]["input_tokens"] == 10
    assert upstream and upstream[0].get_header("X-api-key") == "test-key"
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/proxy/anthropic/v1/messages", body=body,
                 headers={"Content-Type": "application/json", "x-api-key": "bogus"})
    assert conn.getresponse().status == 401
    status, control, _ = _request(port, "/api/control", headers={"Cookie": f"efferents_owner={ada['cluster']['network_token']}"})
    assert control["cluster"]["proxy_spend_usd"] > 0


def test_azure_config_and_proxy_token_boundary(hub, monkeypatch):
    port, ctx, _, cfg, upstream = hub
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "azure-host-key")
    ada, _ = _join(port, "Ada")
    status, config, _ = _request(port, "/api/network/config", headers=_bearer(ada))
    assert status == 200
    assert config["env"]["OPENAI_API_KEY"] == ada["cluster"]["network_token"]
    assert config["env"]["EFFERENTS_API_BASE"].endswith("/proxy/openai/v1")
    assert "ANTHROPIC_API_KEY" not in config["env"]
    assert "azure-host-key" not in json.dumps(config)

    import http.client
    body = json.dumps({"model": "gpt-4.1-nano", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/proxy/openai/v1/chat/completions", body=body,
                 headers={"Content-Type": "application/json",
                          "Authorization": f"Bearer {ada['cluster']['network_token']}"})
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 200
    assert upstream[-1].get_header("Api-key") == "azure-host-key"
    assert upstream[-1].get_header("Authorization") is None

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/proxy/openai/v1/chat/completions", body=body,
                 headers={"Authorization": "Bearer bogus"})
    assert conn.getresponse().status == 401


def test_network_publications_require_a_persisted_three_score_journal(hub):
    _, ctx, _, cfg, _ = hub
    journal = cfg.paths.shared_journal / "journal.md"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("# Journal\n\n<!-- ENTRIES BELOW -->\n\n"
                       "## 2026-09-20 14:00 UTC — c1\n**Lab**: lab-a\n"
                       "**Headline**: Accepted result\n"
                       "critical=6, neutral=7, optimistic=8\n\n"
                       "## 2026-09-20 13:00 UTC — c2\n**Lab**: lab-b\n"
                       "**Headline**: Incomplete review\ncritical=5\n")
    rows = ctx.control.portfolio()["findings"]
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == "c1"
    assert rows[0]["review_scores"] == {"critical": 6, "neutral": 7, "optimistic": 8}

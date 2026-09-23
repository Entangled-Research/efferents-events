"""The terminal path over HTTP: intake.md, config, tracks, register, heartbeat,
journal push, feed, reviews, bind, proxy, and remote labs in the portfolio."""
from __future__ import annotations

import io
import json
import tarfile
import threading
from datetime import datetime, timedelta, timezone
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
    cfg = make_cluster(tmp_path, monkeypatch,
                       labs={"auto_start": False, "max_per_owner": 1,
                             "coder_enabled": True},
                       network={"lab_model": "openai/gpt-5.6-sol"})
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


def test_stopped_remote_lab_does_not_become_stale(hub):
    _, ctx, *_ = hub
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert ctx.hub._status({"ts": old, "status": "stopped"}) == "stopped"
    assert ctx.hub._status({"ts": old, "status": "running"}) == "stale"


def test_intake_md_and_config(hub):
    port, ctx, scripts, cfg, _ = hub
    status, body, headers = _request(port, "/intake.md")
    assert status == 200 and "Launch an efferents research lab" in body["raw"]
    assert f"Hub: http://127.0.0.1:{port}" in body["raw"]
    assert 'curl -fsS -H "Authorization: Bearer $TOKEN"' in body["raw"]
    assert "Do not ask for the event join code or try to join again." in body["raw"]
    assert "python -m efferents.cluster.opencode_setup" in body["raw"]
    joined, hdrs = _join(port, "Ada")
    assert joined["cluster"]["network_token"] == joined["owner_link"].split("=")[1]
    status, config, _ = _request(port, "/api/network/config", headers=_bearer(joined))
    assert status == 200
    assert config["env"]["ANTHROPIC_BASE_URL"].endswith("/proxy/anthropic")
    assert config["env"]["EFFERENTS_NETWORK_TOKEN"] == joined["cluster"]["network_token"]
    assert config["lab_yaml"]["cadence"]["runs_per_digest"] == 3
    assert config["lab_yaml"]["routing"]["owner"] == joined["owner"]["id"]
    assert config["lab_yaml"]["routing"]["pool"].startswith("event:")
    assert config["tracks"][0]["id"] == "coefficient-sweep"
    assert "efferents-events" in config["install"]["pip_spec"]
    # Without a token the machine endpoints are closed.
    status, missing, _ = _request(port, "/api/network/config")
    assert status == 401 and missing["error"] == "Join the event with the code first."
    status, invalid, _ = _request(
        port, "/api/network/config", headers={"Authorization": "Bearer invalid"},
    )
    assert status == 401
    assert "Network token invalid or expired" in invalid["error"]
    assert "join code is different" in invalid["error"]


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


def test_numerical_analysis_lab_appears_under_its_own_journal(hub):
    port, *_ = hub
    owner, headers = _join(port, "Math owner")
    status, body, _ = _request(
        port, "/api/network/labs", method="POST",
        payload={"lab_id": "simpson-quadrature-lab", "domain": "numerical-analysis",
                 "hypothesis": VALID_HYP, "track": "custom-local", "host": "math-laptop"},
        headers=_bearer(owner),
    )
    assert status == 200 and body["registered"]
    status, portfolio, _ = _request(port, "/api/labs", headers=headers)
    assert status == 200
    lab = next(row for row in portfolio["labs"] if row["lab_id"] == "simpson-quadrature-lab")
    assert lab["journal"] == "Journal of Numerical Analysis"


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
    status, runs, _ = _request(port, "/api/labs/ada-lab/runs", headers=bob_hdrs)
    assert status == 200 and runs["remote_detail_unavailable"] is True
    assert runs["history"]["total"] == 7 and runs["history"]["best"] == 0.09
    assert runs["runs"] == []  # a heartbeat count is not a run ledger
    status, verdict, _ = _request(port, "/api/labs/ada-lab/verdict", headers=bob_hdrs)
    assert status == 200 and verdict["remote_detail_unavailable"] is True
    assert verdict["n_runs"] == 7 and verdict["falsifiers"] == []
    status, evidence, _ = _request(port, "/api/labs/ada-lab/evidence", headers=bob_hdrs)
    assert status == 200 and evidence["remote_detail_unavailable"] is True
    status, control, _ = _request(port, "/api/labs/ada-lab/control", headers=ada_hdrs)
    assert control["remote"] is True and control["owner_name"] == "Ada"
    status, body, _ = _request(port, "/api/labs/ada-lab/steer", method="POST",
                               payload={"message": "x"}, headers=ada_hdrs)
    assert status == 409 and "own" in body["error"]

    # A registered lab cannot attribute its submission to another lab.
    status, _, _ = _request(port, "/api/network/labs/ada-lab/journal", method="POST",
        payload={"journal": "## 2026-09-20 14:00 UTC — fake\n**Lab**: someone-else\n"}, headers=A)
    assert status == 403

    # Journal push lands in the hub and, after a sync, in the feed.
    journal = ("# Journal\n\n<!-- ENTRIES BELOW -->\n\n## 2026-09-20 14:00 UTC — c1\n"
               "**Lab**: ada-lab\n**Headline**: Loss fell under 0.1\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n")
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
    assert status == 400  # No owned lab: never return the unrestricted hub.
    status, _, _ = _request(port, "/api/network/feed?lab_id=ada-lab", headers=B)
    assert status == 403
    status, own_feed, _ = _request(port, "/api/network/feed?lab_id=ada-lab", headers=A)
    assert status == 200 and "Loss fell under 0.1" not in own_feed["raw"]
    status, papers, _ = _request(port, "/api/labs/ada-lab/papers", headers=bob_hdrs)
    assert status == 200 and papers == []  # no fabricated accepted card from a raw draft
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


def test_owner_eval_snapshot_ingest_and_owner_scoped_reads(hub):
    import base64
    import hashlib

    port, ctx, _, _, _ = hub
    ada, ada_headers = _join(port, "Ada")
    bob, bob_headers = _join(port, "Bob")
    auth = _bearer(ada)
    reg = {"lab_id": "ada-lab", "domain": "synthetic", "hypothesis": VALID_HYP,
           "track": "coefficient-sweep", "host": "adas-macbook"}
    assert _request(port, "/api/network/labs", method="POST", payload=reg,
                    headers=auth)[0] == 200

    png = b"\x89PNG\r\n\x1a\nsmall-test-image"
    digest = hashlib.sha256(png).hexdigest()
    snapshot = {
        "runs": {"runs": [{"run_id": "run-1"}]},
        "evidence": {"records": [{"run_id": "run-1", "artifacts": [
            {"kind": "plot", "token": digest},
        ]}]},
        "verdict": {"verdict": "survives"},
        "images": {digest: base64.b64encode(png).decode("ascii")},
    }
    status, _, _ = _request(
        port, "/api/network/labs/ada-lab/heartbeat", method="POST",
        payload={"status": "running", "runs": 1, "owner_evals": snapshot}, headers=auth,
    )
    assert status == 200

    saved = json.loads((ctx.hub.lab_dir("ada-lab") / "owner-evals.json").read_text())
    assert saved["images"][digest] == snapshot["images"][digest]
    assert saved["evidence"]["records"][0]["artifacts"][0]["url"] == (
        f"/api/labs/ada-lab/artifacts/{digest}"
    )
    assert saved["synced_at"]

    status, owner_runs, _ = _request(port, "/api/labs/ada-lab/runs", headers=ada_headers)
    assert status == 200 and owner_runs["runs"] == [{"run_id": "run-1"}]
    assert owner_runs["synced_at"] == saved["synced_at"]
    status, viewer_runs, _ = _request(port, "/api/labs/ada-lab/runs", headers=bob_headers)
    assert status == 200 and viewer_runs["remote_detail_unavailable"] is True
    assert viewer_runs["runs"] == []

    status, _, image_headers = _request(
        port, f"/api/labs/ada-lab/artifacts/{digest}", headers=ada_headers,
    )
    assert status == 200 and image_headers["content-type"] == "image/png"
    status, _, _ = _request(
        port, f"/api/labs/ada-lab/artifacts/{digest}", headers=bob_headers,
    )
    assert status == 403


def test_remote_paper_register_requires_accepted_journal_entry(hub):
    port, *_ = hub
    owner, _ = _join(port, "Ada")
    _, viewer_headers = _join(port, "Bob")
    auth = _bearer(owner)
    _request(port, "/api/network/labs", method="POST",
             payload={"lab_id": "ada-lab", "domain": "synthetic", "hypothesis": VALID_HYP},
             headers=auth)
    journal = ("# Journal\n\n<!-- ENTRIES BELOW -->\n\n"
               "## 2026-09-20 14:00 UTC — accepted-one\n"
               "**Lab**: ada-lab\n**Headline**: Reviewed result\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n")

    def paper(campaign, status):
        return (f"---\nlab_id: ada-lab\ncampaign_id: {campaign}\n"
                f"novelty_claim: Result\npublished_at: '2026-09-20'\n"
                f"status: {status}\n---\n\n# Result\n")

    _request(port, "/api/network/labs/ada-lab/journal", method="POST",
             payload={"journal": journal, "papers": {
                 "accepted-one": paper("accepted-one", "preprint"),
                 "unreviewed-one": paper("unreviewed-one", "accepted"),
                 "draft-one": paper("draft-one", "draft"),
                 "rejected-one": paper("rejected-one", "rejected"),
             }}, headers=auth)
    status, papers, _ = _request(port, "/api/labs/ada-lab/papers", headers=viewer_headers)
    assert status == 200
    assert [paper["campaign_id"] for paper in papers] == ["accepted-one"]
    assert papers[0]["status"] == "accepted"


def test_network_evidence_includes_only_same_lab_accepted_manuscripts(hub):
    port, ctx, _, cfg, _ = hub
    owner, _ = _join(port, "Ada")
    auth = _bearer(owner)
    _request(port, "/api/network/labs", method="POST",
             payload={"lab_id": "ada-lab", "domain": "synthetic", "hypothesis": VALID_HYP},
             headers=auth)
    accepted = ("---\nlab_id: ada-lab\ncampaign_id: accepted-one\n"
                "novelty_claim: bounded result\npublished_at: '2026-09-20'\nstatus: accepted\n---\n\n"
                "# Bounded result\n\n| case | error |\n| --- | --- |\n| A | 0.1 |\n")
    mismatch = accepted.replace("accepted-one", "mismatch-one").replace("lab_id: ada-lab", "lab_id: another-lab")
    rejected = accepted.replace("accepted-one", "rejected-one")
    explicitly_rejected = accepted.replace("accepted-one", "explicit-rejection").replace(
        "status: accepted", "status: rejected")
    large = accepted.replace("accepted-one", "large-one") + ("x" * 100_001)
    journal = ("# Journal\n\n<!-- ENTRIES BELOW -->\n\n"
               "## 2026-09-20 14:00 UTC — accepted-one\n**Lab**: ada-lab\n"
               "**Headline**: Reviewed bounded result\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n\n"
               "## 2026-09-20 14:01 UTC — mismatch-one\n**Lab**: ada-lab\n"
               "**Headline**: Mismatched manuscript\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n\n"
               "## 2026-09-20 14:02 UTC — large-one\n**Lab**: ada-lab\n"
               "**Headline**: Large manuscript\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n\n"
               "## 2026-09-20 14:03 UTC — explicit-rejection\n**Lab**: ada-lab\n"
               "**Headline**: Rejected artifact\n"
               "**Scores**: critical=6, neutral=7, optimistic=8 (mean=7.0)\n")
    _request(port, "/api/network/labs/ada-lab/journal", method="POST",
             payload={"journal": journal, "papers": {
                 "accepted-one": accepted, "mismatch-one": mismatch,
                 "rejected-one": rejected, "large-one": large,
                 "explicit-rejection": explicitly_rejected,
             }}, headers=auth)
    from efferents.cluster import sync
    sync.sync_once(cfg, reviews=False)

    findings = ctx.hub.network_evidence()["findings"]
    by_campaign = {item["campaign_id"]: item for item in findings}
    assert by_campaign["accepted-one"]["body"].startswith("## 2026-09-20")
    assert by_campaign["accepted-one"]["manuscript"].startswith("---\nlab_id: ada-lab")
    assert "mismatch-one" in by_campaign and "manuscript" not in by_campaign["mismatch-one"]
    assert "large-one" in by_campaign and "manuscript" not in by_campaign["large-one"]
    assert "explicit-rejection" in by_campaign and "manuscript" not in by_campaign["explicit-rejection"]
    assert "rejected-one" not in by_campaign


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
    assert {config["env"][key] for key in (
        "EFFERENTS_MODEL", "EFFERENTS_MODEL_LIBRARIAN", "EFFERENTS_MODEL_REVIEWER",
        "EFFERENTS_MODEL_REBUTTAL", "EFFERENTS_MODEL_SUPERVISOR",
        "EFFERENTS_MODEL_ANALYST", "EFFERENTS_MODEL_CODER",
    )} == {"openai/gpt-5.6-sol"}
    assert config["lab_yaml"]["autonomy"]["coder_enabled"] is True
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


def test_azure_responses_stream_keeps_tool_reasoning_and_records_usage(hub, monkeypatch):
    port, ctx, _, _, upstream = hub
    monkeypatch.setenv("EFFERENTS_AZURE_OPENAI_ENDPOINT",
                       "https://resource.openai.azure.com/openai/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "azure-host-key")
    ada, _ = _join(port, "Ada")

    class FakeSSE(io.BytesIO):
        status = 200

        def __init__(self):
            completed = {"type": "response.completed", "response": {
                "usage": {"input_tokens": 10, "output_tokens": 5}}}
            super().__init__(("data: " + json.dumps(completed) + "\n\n").encode())
            self.headers = Message()
            self.headers["Content-Type"] = "text/event-stream"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        upstream.append(req)
        return FakeSSE()

    ctx.proxy._open = opener
    request = {"model": "gpt-5.6-sol", "stream": True,
               "input": [{"role": "user", "content": "hi"}],
               "tools": [{"type": "function", "name": "read_file",
                          "parameters": {"type": "object", "properties": {}}}]}
    status, response, headers = _request(
        port, "/proxy/openai/v1/responses", method="POST", payload=request,
        headers=_bearer(ada),
    )
    assert status == 200 and "response.completed" in response["raw"]
    assert headers["content-type"].startswith("text/event-stream")
    assert upstream[-1].full_url.endswith("/openai/v1/responses")
    forwarded = json.loads(upstream[-1].data)
    assert forwarded["reasoning"] == {"effort": "high"}
    assert forwarded["tools"] == request["tools"]
    assert forwarded["max_output_tokens"] == 32768
    assert upstream[-1].get_header("Api-key") == "azure-host-key"
    assert ctx.proxy.spend(ada["owner"]["id"]) > 0


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


def test_zero_lab_limit_is_unlimited(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch, labs={"auto_start": False, "max_per_owner": 0})
    ctx = ClusterContext(cfg, tracks=load_tracks(cfg.tracks_path),
                         client_factory=lambda budget: ScriptedClient([], budget=budget))
    httpd, ctx = make_cluster_server(cfg, port=0, context=ctx, read_ttl_s=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        ada, _ = _join(port, "Ada")
        assert ada["cluster"]["limits"]["labs_per_owner"] == 0
        for n in range(5):
            status, body, _ = _request(port, "/api/network/labs", method="POST",
                                       payload={"lab_id": f"ada-{n}", "hypothesis": VALID_HYP,
                                                "domain": "d"}, headers=_bearer(ada))
            assert status == 200, body
        status, portfolio, _ = _request(port, "/api/labs", headers=_bearer(ada))
        assert len(portfolio["labs"]) == 5
    finally:
        httpd.shutdown()
        httpd.server_close()

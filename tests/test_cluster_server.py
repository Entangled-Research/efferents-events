from __future__ import annotations

import http.client
import json
import threading

import pytest

from efferents.cluster.context import ClusterContext
from efferents.cluster.server import make_cluster_server
from efferents.cluster.tracks import load_tracks
from tests.cluster_helpers import ScriptedClient, hypothesis_block, make_cluster, make_popper_repo


@pytest.fixture
def cluster_server(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch, labs={"auto_start": False})
    scripts: dict = {"replies": []}
    ctx = ClusterContext(
        cfg, tracks=load_tracks(cfg.tracks_path),
        client_factory=lambda budget: ScriptedClient(scripts["replies"], budget=budget),
    )
    httpd, ctx = make_cluster_server(cfg, port=0, context=ctx, read_ttl_s=0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port, ctx, scripts, cfg
    httpd.shutdown()
    httpd.server_close()


def _request(port, path, *, method="GET", payload=None, headers=None, follow=True):
    body = json.dumps(payload).encode() if payload is not None else None
    hdrs = dict(headers or {})
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    out_headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {"raw": raw.decode(errors="replace")}
    return resp.status, data, out_headers


def _cookie(headers) -> dict:
    set_cookie = headers.get("set-cookie", "")
    token = set_cookie.split(";", 1)[0]
    return {"Cookie": token}


def _join(port, name="Ada", code="popper-2026"):
    status, body, headers = _request(port, "/api/join", method="POST",
                                     payload={"code": code, "name": name})
    assert status == 200, body
    hdrs = _cookie(headers)
    hdrs["X-Efferents-CSRF"] = body["csrf_token"]
    return body, hdrs


def test_unjoined_control_has_no_csrf_and_reads_are_401(cluster_server):
    port, *_ = cluster_server
    status, body, _ = _request(port, "/api/control")
    assert status == 200 and body["mode"] == "cluster"
    assert body["cluster"]["joined"] is False and "csrf_token" not in body
    assert _request(port, "/api/labs")[0] == 401
    assert _request(port, "/api/tracks")[0] == 401
    assert _request(port, "/api/intake/sessions")[0] == 401


def test_join_sets_cookie_and_unlocks_reads(cluster_server):
    port, ctx, *_ = cluster_server
    status, _, _ = _request(port, "/api/join", method="POST",
                            payload={"code": "wrong", "name": "Ada"})
    assert status == 403
    body, hdrs = _join(port)
    assert body["owner"]["name"] == "Ada" and body["owner_link"].startswith("/?owner=")
    status, control, _ = _request(port, "/api/control", headers=hdrs)
    assert control["cluster"]["joined"] is True and control["csrf_token"]
    assert control["cluster"]["owner_link"] == body["owner_link"]
    status, tracks, _ = _request(port, "/api/tracks", headers=hdrs)
    assert status == 200 and tracks[0]["id"] == "coefficient-sweep"
    status, portfolio, _ = _request(port, "/api/labs", headers=hdrs)
    assert status == 200 and portfolio["labs"] == []
    # Duplicate names are refused; the join endpoint is rate limited per IP.
    assert _request(port, "/api/join", method="POST",
                    payload={"code": "popper-2026", "name": "ada"})[0] == 409


def test_owner_link_redirect_sets_cookie(cluster_server):
    port, *_ = cluster_server
    body, _ = _join(port)
    status, _, headers = _request(port, body["owner_link"])
    assert status == 302 and headers["location"] == "/#join"
    assert "efferents_owner=" in headers.get("set-cookie", "")
    status, _, headers = _request(port, "/?owner=bogus")
    assert status == 302 and headers["location"] == "/#join"


def test_connect_and_select_are_disabled_in_cluster_mode(cluster_server):
    port, *_ = cluster_server
    _, hdrs = _join(port)
    assert _request(port, "/api/connect", method="POST", payload={"source": "x"}, headers=hdrs)[0] == 404
    assert _request(port, "/api/labs/select", method="POST", payload={"lab_id": "x"}, headers=hdrs)[0] == 404


def test_full_intake_creates_lab_and_enforces_ownership(cluster_server):
    port, ctx, scripts, cfg = cluster_server
    ada_body, ada = _join(port, "Ada")
    bob_body, bob = _join(port, "Bob")

    status, payload, _ = _request(port, "/api/intake/sessions", method="POST", payload={}, headers=ada)
    assert status == 200
    sid = payload["session"]["session_id"]
    scripts["replies"].extend([hypothesis_block()])
    status, payload, _ = _request(port, f"/api/intake/sessions/{sid}/messages", method="POST",
                                  payload={"text": "bigger coefficient, lower loss"}, headers=ada)
    assert status == 200 and payload["session"]["state"] == "drafted"
    # Bob cannot read Ada's session.
    assert _request(port, f"/api/intake/sessions/{sid}", headers=bob)[0] == 404
    status, payload, _ = _request(port, f"/api/intake/sessions/{sid}/approve", method="POST",
                                  payload={}, headers=ada)
    assert payload["session"]["state"] == "approved"
    status, body, _ = _request(port, f"/api/intake/sessions/{sid}/bind", method="POST",
                               payload={"track_id": "coefficient-sweep"}, headers=ada)
    assert status == 409 and "automatic" in body["error"]
    scripts["replies"].extend([
        json.dumps({"action": "existing", "track_id": "coefficient-sweep",
                    "confidence": 0.98, "reason": "compatible"}),
        json.dumps({
            "falsifiers": [{"id": "F1", "description": "Median loss stays >= 0.1",
                            "when": {"column": "synthetic_loss", "agg": "median", "op": ">=",
                                     "value": 0.1, "min_n": 4}}],
            "rationale": "r", "lab_id": "ada-coef",
        }),
    ])
    status, payload, _ = _request(port, f"/api/intake/sessions/{sid}/route", method="POST",
                                  payload={}, headers=ada)
    assert status == 200 and payload["session"]["state"] == "bound"
    status, result, _ = _request(port, f"/api/intake/sessions/{sid}/create", method="POST",
                                 payload={"lab_id": "ada-coef", "falsifiers": ["F1"]}, headers=ada)
    assert status == 200, result
    assert result["lab_id"] == "ada-coef" and result["started"] is False
    assert result["control"]["owner_name"] == "Ada"

    # Everyone joined can read it; only Ada can steer it.
    status, state, _ = _request(port, "/api/labs/ada-coef/state", headers=bob)
    assert status == 200 and state["lab_id"] == "ada-coef"
    status, portfolio, _ = _request(port, "/api/labs", headers=bob)
    assert portfolio["labs"][0]["owner_name"] == "Ada"
    status, body, _ = _request(port, "/api/labs/ada-coef/steer", method="POST",
                               payload={"message": "hijack"}, headers=bob)
    assert status == 403
    status, body, _ = _request(port, "/api/labs/ada-coef/steer", method="POST",
                               payload={"message": "Focus on coefficients above 0.7."}, headers=ada)
    assert status == 200 and body["by"] == "participant:Ada"
    status, body, _ = _request(port, "/api/labs/ada-coef/pause", method="POST",
                               payload={"reason": "coffee"}, headers=ada)
    assert status == 200 and body["queued"] == "pause"
    records = [json.loads(line) for line in
               (cfg.paths.labs / "ada-coef" / "lab" / "steering.jsonl").read_text().splitlines()]
    assert [r["by"] for r in records] == ["participant:Ada", "participant:Ada"]
    # Ada's session now shows the lab, and control reports it as hers.
    status, control, _ = _request(port, "/api/control", headers=ada)
    assert control["cluster"]["my_labs"] == ["ada-coef"]
    status, sessions, _ = _request(port, "/api/intake/sessions", headers=ada)
    assert sessions[0]["state"] == "created" and sessions[0]["lab_id"] == "ada-coef"


def test_mutations_need_csrf_even_when_joined(cluster_server):
    port, *_ = cluster_server
    body, hdrs = _join(port)
    hdrs.pop("X-Efferents-CSRF")
    status, resp, _ = _request(port, "/api/intake/sessions", method="POST", payload={}, headers=hdrs)
    assert status == 403 and "control token" in resp["error"]


@pytest.mark.parametrize("path", ["/api/onboard", "/api/lab/trial", "/api/network/observe"])
def test_single_user_mutations_unavailable_in_cluster(cluster_server, path):
    port, *_ = cluster_server
    _, headers = _join(port)
    assert _request(port, path, method="POST", payload={"confirmed": True}, headers=headers)[0] == 404


@pytest.fixture
def laptop_only_server(tmp_path, monkeypatch):
    """A hub with labs.hosted: false — nothing may run on the host."""
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch, labs={"auto_start": True, "hosted": False})
    scripts: dict = {"replies": []}
    ctx = ClusterContext(
        cfg, tracks=load_tracks(cfg.tracks_path),
        client_factory=lambda budget: ScriptedClient(scripts["replies"], budget=budget),
    )
    httpd, ctx = make_cluster_server(cfg, port=0, context=ctx, read_ttl_s=0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port, ctx, scripts, cfg
    httpd.shutdown()
    httpd.server_close()


def test_hosted_off_refuses_lab_creation(laptop_only_server):
    port, ctx, scripts, cfg = laptop_only_server
    body, ada = _join(port, "Ada")
    assert body["cluster"]["hosted_labs"] is False
    status, control, _ = _request(port, "/api/control", headers=ada)
    assert control["cluster"]["hosted_labs"] is False

    status, payload, _ = _request(port, "/api/intake/sessions", method="POST", payload={}, headers=ada)
    sid = payload["session"]["session_id"]
    scripts["replies"].extend([hypothesis_block()])
    _request(port, f"/api/intake/sessions/{sid}/messages", method="POST",
             payload={"text": "bigger coefficient, lower loss"}, headers=ada)
    _request(port, f"/api/intake/sessions/{sid}/approve", method="POST", payload={}, headers=ada)
    scripts["replies"].extend([
        json.dumps({"action": "existing", "track_id": "coefficient-sweep",
                    "confidence": 0.98, "reason": "compatible"}),
        json.dumps({
            "falsifiers": [{"id": "F1", "description": "Median loss stays >= 0.1",
                            "when": {"column": "synthetic_loss", "agg": "median", "op": ">=",
                                     "value": 0.1, "min_n": 4}}],
            "rationale": "r", "lab_id": "ada-coef",
        }),
    ])
    status, payload, _ = _request(port, f"/api/intake/sessions/{sid}/route", method="POST",
                                  payload={}, headers=ada)
    assert status == 200 and payload["session"]["state"] == "bound"
    # The harness handoff still works; the hosted create path is closed even
    # when the request asks to start the daemon explicitly.
    status, result, _ = _request(port, f"/api/intake/sessions/{sid}/create", method="POST",
                                 payload={"lab_id": "ada-coef", "falsifiers": ["F1"], "start": True},
                                 headers=ada)
    assert status == 409 and "laptop" in result["error"]
    assert not (cfg.paths.labs / "ada-coef").exists()
    assert list(cfg.paths.labs.iterdir()) == []
    status, sessions, _ = _request(port, "/api/intake/sessions", headers=ada)
    assert sessions[0]["state"] == "bound" and not sessions[0].get("lab_id")

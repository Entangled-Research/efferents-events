"""Static guards for the hosted-cluster UI: views exist, no publication
affordances, no inline scripts, scoped routes only."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "efferents" / "dashboard" / "static"


def test_join_and_intake_views_present_without_publication_copy():
    html = (STATIC / "dashboard.html").read_text()
    for needle in ('id="join-view"', 'id="intake-view"', 'id="pause-lab"',
                   'id="resume-lab"', 'id="intake-chat"', 'id="track-picker"',
                   'data-cluster-only', 'data-local-only'):
        assert needle in html, needle
    for banned in ("Private until authorized", "private by default", "data-network-scope",
                   "Public lab", "Make public"):
        assert banned not in html, banned
    assert "<script>" not in html  # CSP script-src 'self': external file only


def test_js_uses_scoped_routes_and_cluster_endpoints():
    js = (STATIC / "dashboard.js").read_text()
    assert "function labPath(kind)" in js
    assert 'postJSON("/api/labs/select"' not in js
    for needle in ('postJSON("/api/join"', '"/api/intake/sessions"', "renderSession(",
                   "function isCluster()", 'openRuntimeDialog("pause")',
                   'openRuntimeDialog("resume")'):
        assert needle in js, needle
    assert "QML" not in js


def test_css_covers_cluster_marks():
    css = (STATIC / "dashboard.css").read_text()
    for needle in (".map-node.mine", ".edge-reviewed", ".chat-turn", ".track-option"):
        assert needle in css, needle

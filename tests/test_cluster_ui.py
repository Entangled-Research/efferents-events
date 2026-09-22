"""Static guards for the hosted-cluster UI: the views and marks exist, the
script stays external, and the harness is the way onto the network."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "efferents" / "dashboard" / "static"
HTML = (STATIC / "dashboard.html").read_text()
JS = (STATIC / "dashboard.js").read_text()
CSS = (STATIC / "dashboard.css").read_text()


def test_cluster_views_exist():
    for needle in ('id="join-view"', 'id="intake-view"', 'id="intake-chat"',
                   'id="track-picker"', 'id="harness-panel"', 'id="harness-instruction"',
                   'data-cluster-only', 'data-local-only', 'data-hosted-only'):
        assert needle in HTML, needle
    for banned in ("Private until authorized", "private by default", "data-network-scope",
                   "Public lab", "Make public"):
        assert banned not in HTML, banned
    assert "<script>" not in HTML  # CSP script-src 'self'


def test_cluster_endpoints():
    for needle in ('"/api/join"', '"/api/intake/sessions"', "/route`", "hosted_labs"):
        assert needle in JS, needle
    assert '"/api/labs/select"' not in JS
    assert "QML" not in JS


def test_harness_first():
    assert 'href="#join" data-route-link="join" data-cluster-only' in HTML
    assert "Connect a lab" in HTML
    assert "New lab</a>" not in HTML
    assert "Optional" in HTML.split('id="intake-view"', 1)[1][:600]
    assert 'href="#join">connect one from your harness' in JS
    assert "Use my approved browser intake session" in JS


def test_css_cluster_marks():
    for needle in (".map-node.mine", ".edge-reviewed", ".chat-turn", ".track-option"):
        assert needle in CSS, needle

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


def test_intake_messages_use_safe_basic_markdown_renderer():
    js = (STATIC / "dashboard.js").read_text()
    assert "function renderMarkdown(value)" in js
    assert '.replace(/\\\\n/g, "\\n")' in js
    assert '.replace(/\\*\\*([^*\\n]+)\\*\\*/g, "<strong>$1</strong>")' in js
    assert 'renderMarkdown(t.text)' in js
    assert 'intake-draft").innerHTML = renderMarkdown' in js


def test_intake_routes_automatically_and_offers_local_harness():
    html = (STATIC / "dashboard.html").read_text()
    js = (STATIC / "dashboard.js").read_text()
    assert "2 · Automatic routing" in html
    assert 'id="harness-panel"' in html
    assert 'id="harness-instruction"' in html
    assert "Choose a track" not in html
    assert "/route`, {})" in js
    assert "Use my approved browser intake session" in js


def test_hosted_lab_creation_is_gated_by_cluster_policy():
    html = (STATIC / "dashboard.html").read_text()
    js = (STATIC / "dashboard.js").read_text()
    # The create panel is driven by intake state, not by the refresh loop.
    assert 'id="binding-panel" aria-labelledby="binding-title" hidden' in html
    assert 'id="binding-panel" aria-labelledby="binding-title" data-hosted-only' not in html
    assert '<span data-hosted-only hidden>No laptop?' in html
    assert "function hostedLabsEnabled()" in js
    assert 'document.querySelectorAll("[data-hosted-only]").forEach((el) => { el.hidden = !hosted; });' in js
    assert "payload.binding && hostedLabsEnabled()" in js


def test_harness_is_the_default_way_onto_the_network():
    html = (STATIC / "dashboard.html").read_text()
    js = (STATIC / "dashboard.js").read_text()
    assert 'data-route-link="intake" data-cluster-only hidden>Sharpen an idea</a>' in html
    assert "New lab</a>" not in html
    assert "Connect your lab from your harness" in html
    assert "Optional · before your harness" in html
    assert 'href="#join" data-cluster-only hidden>+ Connect from your harness</a>' in html
    assert "connect one from your harness (see Join)" in js
    assert "start one under New lab" not in js


def test_css_covers_cluster_marks():
    css = (STATIC / "dashboard.css").read_text()
    for needle in (".map-node.mine", ".edge-reviewed", ".chat-turn", ".track-option"):
        assert needle in css, needle

"""Static guards for the single-lab workspace: entry flow, light-only theme,
external script, collapsible side panels."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "efferents" / "dashboard" / "static"
HTML = (STATIC / "dashboard.html").read_text()
JS = (STATIC / "dashboard.js").read_text()
CSS = (STATIC / "dashboard.css").read_text()


def test_entry_flow_present():
    for needle in ('id="connect-form"', 'id="steer-form"', 'data-route-view="observe"',
                   'id="runtime-confirm-check"', 'data-intake-tab="agent"',
                   'data-intake-tab="submit"'):
        assert needle in HTML, needle


def test_paused_demo_copy():
    assert "Paused demo · no model calls" in JS
    assert "QML" not in JS  # the connection bar shows the real source, never demo copy


def test_light_only_theme():
    assert CSS.startswith(":root {\n  color-scheme: light;")
    assert ':root[data-theme="dark"]' not in CSS
    assert "prefers-color-scheme" not in CSS
    assert 'id="theme-toggle"' not in HTML
    assert "efferents-theme" not in JS
    assert '<meta name="color-scheme" content="light">' in HTML


def test_script_is_external():
    assert '<script src="/static/dashboard.js"></script>' in HTML
    assert "<script>" not in HTML


def test_side_panels_collapse():
    assert HTML.count("data-panel-toggle") == 2
    assert ".panel.collapsed" in CSS


def test_event_network_shows_per_lab_spend_and_keeps_owner_cap_separate():
    assert "function labSpendMarkup(lab)" in JS
    assert "if (!isCluster() || !lab.budget) return \"\";" in JS
    assert "LAB MODEL SPEND · ESTIMATE" in JS
    assert "lab cap`" in JS
    assert "Above lab cap" in JS
    assert "proxy_spend_usd" in JS
    assert "proxy_cap_usd" in JS
    assert "your event spend" in JS
    assert "clusterNetwork && isJoined()" in JS
    assert "!clusterNetwork && portfolioState.labs.length > 0" in JS
    assert "network-lab-spend-track" in CSS
    assert ".network-lab-spend.over-cap .network-lab-spend-track span { background: var(--terracotta); }" in CSS

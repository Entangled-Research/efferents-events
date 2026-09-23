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
    assert "LAB SPEND" in JS
    assert "your total spend" in JS
    assert "owner_budget" in JS
    assert "lab cap`" not in JS
    assert "Above lab cap" not in JS
    assert 'id="selected-lab-spend"' in HTML


def test_returning_identity_and_diagnostics_are_available():
    for element in ("login-form", "recovery-panel", "copy-recovery", "diagnostics-view",
                    "refresh-diagnostics", "copy-diagnostics", "diagnostics-report"):
        assert f'id="{element}"' in HTML
    assert 'getJSON("/api/diagnostics")' in JS
    assert 'postJSON("/api/login"' in JS

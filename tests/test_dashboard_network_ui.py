"""Static guards for the network map and the shared visual contract."""
from pathlib import Path

from efferents.dashboard.report_theme import REPORT_CSS

STATIC = Path(__file__).resolve().parents[1] / "efferents" / "dashboard" / "static"
PROGRESS = (STATIC.parents[1] / "agents" / "progress.py").read_text()
HTML = (STATIC / "dashboard.html").read_text()
JS = (STATIC / "dashboard.js").read_text()
CSS = (STATIC / "dashboard.css").read_text()


def test_portfolio_and_map_present():
    for needle in ('id="lab-rail"', 'id="lab-list"', 'data-route-view="network"',
                   'id="lab-map"', 'id="event-admin-panel"'):
        assert needle in HTML, needle
    for banned in ("data-network-scope", "Private until authorized", "private by default",
                   'src="/prototypes/event-network.html"'):
        assert banned not in HTML, banned
    assert 'getJSON("/api/labs")' in JS
    assert '"/api/labs/select"' not in JS  # selection is per browser, never server-wide
    assert 'id="lab-rail-toggle"' not in HTML
    assert 'id="lab-tabs"' in HTML
    assert 'getElementById("lab-tabs")' in JS and 'data-tab="${esc(labId)}"' in JS


def test_network_tabs_show_visible_labs_without_opening_observers():
    assert 'route === "network"' in JS
    assert '? portfolioState.labs.map((lab) => lab.lab_id)' in JS
    assert 'strip.hidden = !["network", "publication", "journal", "observe"].includes(route) || visibleTabIds.length === 0;' in JS
    assert 'route === "observe" ? `<span class="tab-close"' in JS


def test_map_is_pan_zoom_viewport():
    assert 'id="lab-map"' in HTML and 'tabindex="0"' in HTML
    world = HTML.index('id="network-world"')
    for layer in ("network-lines", "network-journals", "network-nodes", "network-ideas"):
        assert HTML.index(f'id="{layer}"') > world, layer
    for control in ("in", "out", "fit"):
        assert f'data-map-zoom="{control}"' in HTML, control
    assert ".map-controls" in CSS


def test_visual_contract_tokens():
    for token in ("--bg: #f1ede2;", "--panel: #faf8f0;", "--signal: #2d5379;",
                  "--terracotta: #a8502b;", "--mustard: #a8842d;", "--orange: #c05a2e;"):
        assert token in CSS, token
    for banned in ("#03befc", "#0057ff", "color-mix", "backdrop-filter", "#f7fbff"):
        assert banned not in CSS, banned
    assert ">ℯ</span>" in HTML and ">EF</span>" not in HTML
    for generated in (REPORT_CSS, PROGRESS):
        assert "color-scheme: light;" in generated
        assert "#03befc" not in generated and "linear-gradient" not in generated
        assert "EF / RESEARCH RECORD" not in generated


def test_evidence_panels_present():
    for needle in ('id="metric-eligible"', 'id="metric-median"', 'id="metric-iqr"',
                   'id="evidence-panel"'):
        assert needle in HTML, needle
    assert '"/api/evidence"' in JS
    assert ".evidence-gallery" in CSS


def test_verdict_belongs_to_idea():
    assert "lab-verdict" not in JS
    assert "Ideas ·" in JS
    assert "Idea verdict" in HTML


def test_journal_directory_and_exchange_panel():
    for removed in ("Labs communicate only", "exchange-count",
                    "exchange-explanation"):
        assert removed not in HTML and removed not in JS, removed
    assert 'id="exchange-panel"' in HTML
    assert 'id="journal-view"' in HTML
    assert 'id="journal-publication-list"' in HTML

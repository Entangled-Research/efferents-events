import json

from efferents.agents.conference import _rows
from efferents.cluster import subscriptions, sync
from efferents.cluster.network import NetworkHub
from efferents.cluster.owners import Owner
from efferents.dashboard.control import ControlError
from tests.cluster_helpers import make_cluster
import pytest


def _entry(lab, cid="p1"):
    return {"lab_id": lab, "campaign_id": cid,
            "body": f"## 2026-09-23 10:00 UTC — {cid}\n**Lab**: {lab}\n"
                    "**Scores**: critical=6, neutral=7, optimistic=8\n"
                    "### Accepted manuscript\n\n> ## Methods\n> Measured procedure\n"}


def test_cross_journal_cadence_and_receipts_require_durable_ack(tmp_path):
    d = tmp_path / "chem-lab"
    entries = [_entry("physics-lab"), _entry("chem-lab", "self"), _entry("unknown-lab")]
    domains = {"physics-lab": "physics", "chem-lab": "chemistry", "unknown-lab": "television"}
    for visit in range(1, 5):
        assert "Measured procedure" not in subscriptions.visit(
            d, "chem-lab", "chemistry", entries, domains, now=visit * 60, interval=60)
    content = subscriptions.visit(d, "chem-lab", "chemistry", entries, domains, now=300, interval=60)
    assert "physics-lab" in content and "unknown-lab" not in content
    assert subscriptions.observations(tmp_path) == []  # queued / GET is not durable receipt
    assert subscriptions.acknowledge(d, {"invented"}) == 0
    assert subscriptions.acknowledge(d, {"journal:physics-lab:p1"}) == 1
    assert subscriptions.acknowledge(d, {"journal:physics-lab:p1"}) == 0
    received = subscriptions.observations(tmp_path)
    assert len(received) == 1 and received[0]["track"] == "interdisciplinary"
    assert received[0]["journal"] == "Physics & Dynamics"
    assert "not a replication" in received[0]["meaning"]
    subscriptions.visit(d, "chem-lab", "chemistry", entries, domains, now=301, interval=60)
    assert len(_rows(d / "attendance.jsonl")) == 5


def test_hub_feed_and_ack_are_owner_scoped_and_chemistry_journal_exists(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    hub = NetworkHub(cfg, {})
    owner = Owner("owner-a", "ChemistryNerd", "token-a", "2026-09-23")
    other = Owner("owner-b", "Other", "token-b", "2026-09-23")
    hub.register(owner, {"lab_id": "chem-lab", "domain": "chemistry",
                         "hypothesis": "falsifiability_gate: passed"})
    assert {"name": "Chemistry"} in hub.network_evidence()["journals"]
    d = cfg.paths.shared_journal / "subscriptions" / "chem-lab"
    subscriptions.visit(d, "chem-lab", "chemistry", [_entry("source-lab")],
                        {"source-lab": "chemistry"}, now=60, interval=60)
    assert "source-lab" in hub.subscribed_feed(owner, "chem-lab")
    assert subscriptions.observations(d.parent) == []
    with pytest.raises(ControlError):
        hub.subscribed_feed(other, "chem-lab")
    with pytest.raises(ControlError):
        hub.acknowledge_feed(other, "chem-lab", {"received": ["journal:source-lab:p1"]})
    assert hub.acknowledge_feed(owner, "chem-lab", {"received": ["journal:source-lab:p1"]})["receipts_added"] == 1


def test_collect_requires_manuscript_and_never_exports_a_draft(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    sub = tmp_path / "submission"
    paper = sub / "paper"
    paper.mkdir(parents=True)
    entry = _entry("source-lab")
    journal = paper / "journal.md"
    journal.write_text(entry["body"])
    labs = [{"lab_id": "source-lab", "domain": "physics", "submission_dir": sub, "lab_root": sub / "lab"}]
    assert sync.collect(cfg, labs) == []
    manuscript = paper / "p1.md"
    manuscript.write_text("---\nlab_id: source-lab\ncampaign_id: p1\nstatus: draft\n---\nPrivate draft")
    assert sync.collect(cfg, labs) == []
    manuscript.write_text(manuscript.read_text().replace("status: draft", "status: preprint"))
    assert len(sync.collect(cfg, labs)) == 1
    assert "Private draft" in (cfg.paths.shared_journal / "manuscripts" / "source-lab__p1.md").read_text()

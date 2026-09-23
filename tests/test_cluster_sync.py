from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from efferents.agents import federation
from efferents.cluster import crossreview, sync
from efferents.registry import LabRecord, Registry
from tests.cluster_helpers import make_cluster

ENTRY = (
    "# Journal\n\n<!-- ENTRIES BELOW -->\n\n"
    "## 2026-09-20 14:00 UTC — {cid}\n"
    "**Lab**: {lab}\n**Student**: primary\n**Headline**: {headline}\n"
    "**Paper**: [{cid}.md]({cid}.md)\n"
)


def _lab(cfg, lab_id, domain, *, journal_entries=()):
    sub = cfg.paths.labs / lab_id
    (sub / "lab").mkdir(parents=True)
    (sub / "lab" / "runs.sqlite").write_bytes(b"")
    (sub / "lab" / "digests").mkdir()
    (sub / "lab" / "digests" / "d1.md").write_text(f"# digest of {lab_id}\n")
    (sub / "lab.yaml").write_text(yaml.safe_dump({"lab_id": lab_id, "domain": domain}))
    (sub / "hypothesis.md").write_text(f"---\nslug: {lab_id}\n---\n# {lab_id} claim\n")
    if journal_entries:
        text = "# Journal\n\n<!-- ENTRIES BELOW -->\n"
        for cid, headline in journal_entries:
            text += ("\n## 2026-09-20 14:00 UTC — " + cid + f"\n**Lab**: {lab_id}\n"
                     f"**Headline**: {headline}\n**Scores**: critical=6, neutral=7, optimistic=8\n")
            (sub / "paper").mkdir(exist_ok=True)
            (sub / "paper" / f"{cid}.md").write_text(f"# paper {cid}\n\nbody\n")
        (sub / "paper").mkdir(exist_ok=True)
        (sub / "paper" / "journal.md").write_text(text)
    Registry().register(LabRecord(lab_id=lab_id, submission_dir=str(sub),
                                  lab_root=str(sub / "lab"), pid=0,
                                  started_at="", status="running"))
    return sub


class ReviewClient:
    def __init__(self, budget):
        self.messages = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps({
                "critique": "Seed 3 looks like an outlier (lab-a run_01).",
                "technique": "Report seed-paired deltas.",
                "suggestion": "Sweep coefficient over {0.6, 0.7, 0.8}.",
                "headline": "Try a finer coefficient sweep",
                "cited_runs": ["lab-a run_01"],
            }))],
            usage=SimpleNamespace(input_tokens=500, output_tokens=100),
        )


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, sync={"reviewers_per_entry": 2})
    a = _lab(cfg, "lab-a", "synthetic", journal_entries=[("c1", "Loss falls under 0.1")])
    b = _lab(cfg, "lab-b", "synthetic")
    c = _lab(cfg, "lab-c", "other")
    return cfg, a, b, c


def test_collect_and_distribute_are_idempotent(cluster):
    cfg, a, b, c = cluster
    summary = sync.sync_once(cfg, reviews=False)
    assert summary["new_entries"] == 1 and summary["fan_out_added"] == 1
    hub = (cfg.paths.shared_journal / "journal.md").read_text()
    assert "**Lab**: lab-a" in hub and "Loss falls under 0.1" in hub
    assert (cfg.paths.shared_journal / "entries" / "lab-a__c1.md").exists()
    for other in (b,):
        ext = federation.parse_journal_entries((other / "paper" / "external_journal.md").read_text())
        assert [(e["lab_id"], e["campaign_id"]) for e in ext] == [("lab-a", "c1")]
    assert not (a / "paper" / "external_journal.md").exists() or not federation.parse_journal_entries(
        (a / "paper" / "external_journal.md").read_text())
    again = sync.sync_once(cfg, reviews=False)
    assert again["new_entries"] == 0 and again["fan_out_added"] == 0
    assert (cfg.paths.shared_journal / "index.md").read_text().count("lab-a / c1") == 1


def test_subscription_never_starts_direct_crossreviews_or_spending(cluster):
    cfg, a, b, c = cluster
    def forbidden(*args, **kwargs):
        raise AssertionError("Journal delivery must not run direct reviews")
    summary = sync.sync_once(cfg, reviews=True, client_factory=forbidden)
    assert summary["new_entries"] == 1 and summary["reviews"] == 0
    assert not cfg.paths.reviews_ledger.exists()
    assert not (a / "paper" / "incoming_reviews.md").exists()
    received = (b / "paper" / "external_journal.md").read_text()
    assert "### Accepted manuscript" in received and "> # paper c1" in received


def test_select_reviewers_deterministic_and_spread():
    labs = [{"lab_id": f"line{i}", "domain": "d" if i % 2 else "e",
             "lab_root": Path("/nonexistent")} for i in range(5)]
    entry = {"lab_id": "l0", "campaign_id": "c", "sha256": "abc", "domain": "d"}
    # No runs.sqlite → nobody qualifies.
    assert crossreview.select_reviewers(entry, labs, n=2, same_domain_first=True, existing=[]) == []


def test_remote_labs_join_the_shared_journal(tmp_path, monkeypatch):
    """A laptop lab known only through the hub is collected, fanned out to, and reviewed."""
    cfg = make_cluster(tmp_path, monkeypatch)
    _lab(cfg, "hosted-b", "synthetic")
    remote = cfg.paths.root / "network" / "labs" / "laptop-a"
    (remote / "paper").mkdir(parents=True)
    (remote / "registration.json").write_text(json.dumps({"lab_id": "laptop-a", "owner_id": "o1",
                                                          "owner_name": "Ada", "domain": "synthetic"}))
    (remote / "hypothesis.md").write_text("---\nslug: a\n---\n# claim\n")
    (remote / "heartbeat.json").write_text(json.dumps({"ts": "2999-01-01T00:00:00+00:00",
                                                       "status": "running", "runs": 4}))
    (remote / "paper" / "journal.md").write_text(
        "# J\n\n<!-- ENTRIES BELOW -->\n\n## 2026-09-20 14:00 UTC — c7\n**Lab**: laptop-a\n**Headline**: remote finding\n**Scores**: critical=6, neutral=7, optimistic=8\n")
    (remote / "paper" / "c7.md").write_text("# Accepted manuscript\nActual run provenance.\n")
    summary = sync.sync_once(cfg, reviews=True, client_factory=ReviewClient)
    assert summary["labs"] == 2 and summary["new_entries"] == 1 and summary["reviews"] == 0
    reviews = crossreview.list_reviews(cfg.paths)
    assert reviews == []
    assert not (remote / "paper" / "incoming_reviews.md").exists()
    hosted_ext = (cfg.paths.labs / "hosted-b" / "paper" / "external_journal.md").read_text()
    assert "remote finding" in hosted_ext

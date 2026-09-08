from __future__ import annotations

import json
from pathlib import Path

from efferents.cluster import edges as ed


def _cluster(tmp_path: Path) -> Path:
    root = tmp_path / "c"
    reviews = root / "shared_journal" / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "b__a__c1.md").write_text(
        "---\nreviewer_lab: lab-b\nreviewed_lab: lab-a\ncampaign_id: c1\n"
        "ts: 2026-09-20T14:32:10Z\nstatus: open\n---\n## Critique\nx\n"
    )
    (reviews / "self.md").write_text("---\nreviewer_lab: lab-a\nreviewed_lab: lab-a\n---\n")
    deps = root / "labs" / "lab-c" / "lab"
    deps.mkdir(parents=True)
    (deps / "foundational_deps.jsonl").write_text(
        json.dumps({"lab_id": "lab-a", "campaign_id": "c1", "ts": "t"}) + "\n"
        + json.dumps({"lab_id": "lab-a", "campaign_id": "c1", "ts": "t2"}) + "\n"
        + "not json\n"
    )
    repro = root / "labs" / "lab-b" / "paper"
    repro.mkdir(parents=True)
    (repro / "reproductions.md").write_text(
        "# Reproductions\n\n## 2026-09-20 15:00 UTC — lab-a/c1\n\n**Status**: verified\n\n"
        "## 2026-09-20 15:30 UTC — lab-z/c9\n\n**Status**: failed\n"
    )
    return root


def test_all_edge_kinds_filtered_to_known_labs(tmp_path):
    root = _cluster(tmp_path)
    labs = [{"lab_id": "lab-a"}, {"lab_id": "lab-b"}, {"lab_id": "lab-c"}]
    edges = ed.derive_edges(labs, root)
    kinds = {(e["kind"], e["source"], e["target"]) for e in edges}
    assert kinds == {
        ("reviewed", "lab-b", "lab-a"),
        ("cited", "lab-c", "lab-a"),
        ("reproduced", "lab-b", "lab-a"),
    }
    reproduced = next(e for e in edges if e["kind"] == "reproduced")
    assert reproduced["status"] == "verified" and reproduced["campaign_id"] == "c1"
    assert all(e["path"] for e in edges)
    assert ed.edge_summary(edges) == {"reviewed": 1, "cited": 1, "reproduced": 1}


def test_missing_dirs_are_fine(tmp_path):
    assert ed.derive_edges([{"lab_id": "x"}], tmp_path) == []

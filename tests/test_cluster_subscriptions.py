from efferents.cluster import subscriptions
from efferents.agents.conference import _rows


def entry(author, campaign="c1", reviewed=True):
    return {
        "lab_id": author,
        "campaign_id": campaign,
        "body": f"## 2026-09-23 12:00 UTC — {campaign}\n**Lab**: {author}\n"
        + ("**Scores**: critical=6, neutral=7, optimistic=8\n" if reviewed else ""),
    }


def test_home_reads_and_rare_related_visits_survive_restart(tmp_path):
    domains = {
        "reader": "physics",
        "home": "mechanics",
        "related": "math",
        "unrelated": "literature",
    }
    entries = [
        entry("home"),
        entry("related"),
        entry("unrelated"),
        entry("reader"),
        entry("home", "draft", False),
    ]
    for visit in range(1, 6):
        feed = subscriptions.visit(
            tmp_path,
            "reader",
            "physics",
            entries,
            domains,
            now=visit * 120,
            interval=120,
        )
        assert "**Lab**: home" in feed
        assert ("**Lab**: related" in feed) == (visit == 5)
        assert "**Lab**: unrelated" not in feed and "draft" not in feed
        subscriptions.visit(
            tmp_path,
            "reader",
            "physics",
            entries,
            domains,
            now=visit * 120 + 1,
            interval=120,
        )
    assert len(_rows(tmp_path / "attendance.jsonl")) == 5
    assert len(_rows(tmp_path / "deliveries.jsonl")) == 2
    assert not (tmp_path / "receipts.jsonl").exists()
    subscriptions.acknowledge(tmp_path)
    subscriptions.acknowledge(tmp_path)
    assert len(_rows(tmp_path / "receipts.jsonl")) == 2
    assert _rows(tmp_path / "receipts.jsonl")[-1]["track"] == "interdisciplinary"
    assert subscriptions.feed(tmp_path) == feed


def test_visit_reads_at_most_three_home_and_one_cross_paper(tmp_path):
    domains = {"home": "physics", "cross": "math"}
    entries = [entry("home", f"h{i}") for i in range(20)] + [
        entry("cross", f"c{i}") for i in range(20)
    ]
    for visit in range(1, 11):
        subscriptions.visit(
            tmp_path,
            "reader",
            "physics",
            entries,
            domains,
            now=visit * 120,
            interval=120,
        )
    sessions = _rows(tmp_path / "attendance.jsonl")
    assert all(
        len(row["received"]) <= (4 if row["visit"] % 5 == 0 else 3) for row in sessions
    )
    assert (
        len(
            [
                row
                for row in _rows(tmp_path / "deliveries.jsonl")
                if row["track"] == "interdisciplinary"
            ]
        )
        == 2
    )

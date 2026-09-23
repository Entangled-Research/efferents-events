"""Durable, bounded home-journal reads and occasional related STEM visits."""
from __future__ import annotations

import fcntl
from pathlib import Path

from efferents.agents.conference import _append, _rows
from efferents.journal.reviews import PERSONAS, review_scores
from efferents.journal.provenance import publication_digest
from efferents.journals import INTERDISCIPLINARY_EVERY, journal_for_domain, related_stem_domains


def publication_id(entry: dict) -> str:
    return f"journal:{entry['lab_id']}:{entry['campaign_id']}"


def visit(directory: Path, lab_id: str, domain: str, entries: list[dict],
          domains: dict[str, str], *, now: float, interval: float) -> str:
    """Advance at most once per sync interval; repeat reads cannot hurry visits."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sessions = _rows(directory / "attendance.jsonl")
        deliveries = _rows(directory / "deliveries.jsonl")
        seen = {row["finding_id"] for row in deliveries}
        if not sessions or now - sessions[-1]["at"] >= max(60, interval):
            number = len(sessions) + 1
            same, cross = [], []
            for entry in entries:
                source = entry.get("lab_id")
                source_domain = domains.get(source)
                if (source == lab_id or source_domain is None or publication_id(entry) in seen
                        or set(review_scores(entry["body"])) != set(PERSONAS)):
                    continue
                if journal_for_domain(source_domain) == journal_for_domain(domain):
                    same.append(entry)
                elif related_stem_domains(source_domain, domain):
                    cross.append(entry)
            selected = same[:3] + (cross[:1] if number % INTERDISCIPLINARY_EVERY == 0 else [])
            for entry in selected:
                _append(directory / "deliveries.jsonl", {
                    "finding_id": publication_id(entry), "source": entry["lab_id"], "target": lab_id,
                    "track": "field" if entry in same else "interdisciplinary", "at": now,
                    "visit": number, "body": entry["body"],
                    "journal": journal_for_domain(domains[entry["lab_id"]]),
                    "source_sha256": publication_digest(entry["body"]),
                })
            _append(directory / "attendance.jsonl", {"at": now, "visit": number,
                    "received": [publication_id(entry) for entry in selected]})
        return feed(directory)


def feed(directory: Path) -> str:
    return "# Subscribed journal papers\n\n" + "\n\n".join(
        row["body"] for row in _rows(directory / "deliveries.jsonl"))


def acknowledge(directory: Path, finding_ids: set[str] | None = None) -> int:
    """Acknowledge durably stored publications; GET delivery alone is not receipt."""
    count = 0
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        seen = {row["finding_id"]: row.get("source_sha256") for row in _rows(directory / "receipts.jsonl")}
        for delivery in _rows(directory / "deliveries.jsonl"):
            digest = delivery.get("source_sha256") or publication_digest(delivery["body"])
            if (seen.get(delivery["finding_id"]) != digest
                    and (finding_ids is None or delivery["finding_id"] in finding_ids)):
                count += 1
                seen[delivery["finding_id"]] = digest
                _append(directory / "receipts.jsonl", {
                    **{k: v for k, v in delivery.items() if k != "body"},
                    "source_sha256": digest,
                    "kind": "observation", "meaning": "Journal feed received; not a replication",
                })

    return count


def observations(root: Path) -> list[dict]:
    latest = {}
    for path in sorted(root.glob("*/receipts.jsonl")):
        for row in _rows(path):
            latest[(row["target"], row["finding_id"])] = row
    return list(latest.values())[-200:]

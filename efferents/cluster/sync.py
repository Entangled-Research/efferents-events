"""Shared-journal sync: hub, fan-out, cross-lab reviews, index.

Runs as its own process (``efferents cluster sync --loop``). Reads every
lab's ``paper/journal.md``, publishes new entries into ``shared_journal/``
(hub ``journal.md`` + one file per entry + ``index.jsonl``), fans the hub
out to every other lab's ``paper/external_journal.md`` with the existing
federation importer, asks sibling labs to review new entries, and feeds
those reviews back to the authors. Writes only under ``shared_journal/``
and ``labs/<id>/paper/``; never under ``lab/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from efferents.agents import federation
from efferents.cluster import crossreview
from efferents.cluster.config import ClusterConfig, write_event
from efferents.registry import Registry

HUB_HEADER = (
    "# Shared journal — every accepted entry from every lab in this cluster\n\n"
    "Append-only, newest first. Built by `efferents cluster sync`. Each entry is\n"
    "the originating lab's text verbatim; labs read this hub through their\n"
    "own `paper/external_journal.md`.\n\n"
    "<!-- ENTRIES BELOW -->\n"
)
SENTINEL = "<!-- ENTRIES BELOW -->"
INCOMING_HEADER = (
    "# Reviews of this lab's entries by sibling labs\n\n"
    "Append-only. Written by `efferents cluster sync`; each entry names the\n"
    "reviewing lab and links the full review under shared_journal/reviews/.\n\n"
    "<!-- ENTRIES BELOW -->\n"
)


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _labs(cfg: ClusterConfig) -> list[dict[str, Any]]:
    out = []
    for record in Registry().list():
        sub = Path(record.submission_dir)
        if not sub.is_dir():
            continue
        domain = None
        try:
            import yaml  # noqa: PLC0415
            domain = (yaml.safe_load((sub / "lab.yaml").read_text()) or {}).get("domain")
        except Exception:
            pass
        out.append({"lab_id": record.lab_id, "submission_dir": sub,
                    "lab_root": Path(record.lab_root), "domain": domain,
                    "running": record.status == "running"})
    return out


def _index_keys(paths) -> set[tuple[str, str]]:
    index = paths.shared_journal / "index.jsonl"
    keys: set[tuple[str, str]] = set()
    if index.is_file():
        for line in index.read_text().splitlines():
            try:
                rec = json.loads(line)
                keys.add((rec["lab_id"], rec["campaign_id"]))
            except (ValueError, KeyError):
                continue
    return keys


def collect(cfg: ClusterConfig, labs: list[dict]) -> list[dict]:
    """Publish new journal entries into the hub. Returns the new entries."""
    sj = cfg.paths.shared_journal
    (sj / "entries").mkdir(parents=True, exist_ok=True)
    hub = sj / "journal.md"
    if not hub.exists():
        hub.write_text(HUB_HEADER)
    known = _index_keys(cfg.paths)
    new_entries: list[dict] = []
    for lab in labs:
        for journal in (lab["submission_dir"] / "paper" / "journal.md",
                        lab["lab_root"] / "paper" / "journal.md"):
            if not journal.is_file():
                continue
            for entry in federation.parse_journal_entries(journal.read_text()):
                lab_id = entry.get("lab_id") or lab["lab_id"]
                key = (lab_id, entry["campaign_id"])
                if key in known:
                    continue
                known.add(key)
                body = entry["body"].rstrip()
                if not entry.get("lab_id"):
                    # Stamp the origin so every reader can attribute it.
                    head, _, rest = body.partition("\n")
                    body = f"{head}\n**Lab**: {lab_id}\n{rest}".rstrip()
                digest = hashlib.sha256(body.encode()).hexdigest()
                rec = {
                    "ts": entry["ts"], "lab_id": lab_id, "campaign_id": entry["campaign_id"],
                    "headline": entry.get("headline"), "domain": lab.get("domain"),
                    "source_path": str(journal), "sha256": digest,
                    "published_at": _now_str(),
                }
                entry_file = sj / "entries" / f"{lab_id}__{entry['campaign_id']}.md"
                entry_file.write_text(
                    "---\n" + "\n".join(f"{k}: {v}" for k, v in rec.items() if v is not None)
                    + "\n---\n\n" + body + "\n"
                )
                content = hub.read_text()
                marker = content.index(SENTINEL) + len(SENTINEL)
                hub.write_text(content[:marker] + "\n\n" + body + "\n" + content[marker:])
                with (sj / "index.jsonl").open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
                new_entries.append({**rec, "body": body, "submission_dir": lab["submission_dir"]})
    return new_entries


def distribute(cfg: ClusterConfig, labs: list[dict]) -> dict[str, int]:
    """Fan the hub out to every lab's external journal (dedup built in)."""
    hub = cfg.paths.shared_journal / "journal.md"
    added: dict[str, int] = {}
    if not hub.is_file():
        return added
    for lab in labs:
        out = lab["submission_dir"] / "paper" / "external_journal.md"
        try:
            result = federation.consume_external_journal(
                source=hub, out_path=out, our_lab_id=lab["lab_id"],
            )
        except FileNotFoundError:
            continue
        added[lab["lab_id"]] = int(result.get("n_added", 0))
    return added


def feed_back(cfg: ClusterConfig, review: dict, author_dir: Path) -> Path:
    """Append one review summary to the author's paper/incoming_reviews.md."""
    path = author_dir / "paper" / "incoming_reviews.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(INCOMING_HEADER)
    body = (
        f"## {_now_str()} — {review['campaign_id']}\n"
        f"**Lab**: {review['reviewer_lab']}\n"
        f"**Headline**: {review['headline']}\n"
        f"**Review**: {review['path']}\n\n"
        f"{review['body'][:1200]}\n"
    )
    content = path.read_text()
    if SENTINEL in content:
        marker = content.index(SENTINEL) + len(SENTINEL)
        path.write_text(content[:marker] + "\n\n" + body + content[marker:])
    else:
        path.write_text(content.rstrip() + "\n\n" + body)
    return path


def rebuild_index(cfg: ClusterConfig) -> Path:
    """Deterministic human-readable index of the shared journal."""
    sj = cfg.paths.shared_journal
    entries = []
    index = sj / "index.jsonl"
    if index.is_file():
        for line in index.read_text().splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    reviews = crossreview.list_reviews(cfg.paths)
    by_target: dict[tuple[str, str], list[dict]] = {}
    for r in reviews:
        by_target.setdefault((r["reviewed_lab"], r["campaign_id"]), []).append(r)
    lines = [f"# {cfg.name} — shared journal index", "",
             f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} · "
             f"{len(reviews)} cross-lab review{'s' if len(reviews) != 1 else ''}", ""]
    for e in sorted(entries, key=lambda x: x.get("ts") or "", reverse=True):
        lines.append(f"## {e['lab_id']} / {e['campaign_id']} — {e.get('ts')}")
        if e.get("headline"):
            lines.append(f"{e['headline']}")
        lines.append(f"- entry: `entries/{e['lab_id']}__{e['campaign_id']}.md`")
        for r in by_target.get((e["lab_id"], e["campaign_id"]), []):
            lines.append(f"- review by `{r['reviewer_lab']}` ({r.get('status', 'open')}): "
                         f"{r.get('headline', '')} — `reviews/{Path(r['path']).name}`")
        lines.append("")
    out = sj / "index.md"
    out.write_text("\n".join(lines).rstrip() + "\n")
    return out


def sync_once(cfg: ClusterConfig, *, reviews: bool = True, client_factory=None) -> dict:
    labs = _labs(cfg)
    new_entries = collect(cfg, labs)
    added = distribute(cfg, labs)
    n_reviews = 0
    if reviews and new_entries:
        reviewer = crossreview.Reviewer(cfg, client_factory=client_factory)
        budget_left = cfg.sync.max_reviews_per_tick
        for entry in new_entries:
            if budget_left <= 0:
                break
            for review in reviewer.review_entry(entry, labs):
                feed_back(cfg, review, Path(entry["submission_dir"]))
                n_reviews += 1
                budget_left -= 1
                if budget_left <= 0:
                    break
    crossreview.mark_adopted(cfg.paths)
    rebuild_index(cfg)
    summary = {"ts": _now_str(), "labs": len(labs), "new_entries": len(new_entries),
               "fan_out_added": sum(added.values()), "reviews": n_reviews}
    if new_entries or n_reviews:
        write_event(cfg.paths, "sync", **summary)
    return summary


def run(cfg: ClusterConfig, *, loop: bool, reviews: bool = True) -> None:
    review_key = os.environ.get("EFFERENTS_REVIEW_API_KEY")
    if review_key:
        os.environ["ANTHROPIC_API_KEY"] = review_key
    while True:
        try:
            summary = sync_once(cfg, reviews=reviews)
            print(f"[sync] {summary}", flush=True)
        except Exception as e:
            print(f"[sync] failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if not loop:
            return
        time.sleep(cfg.sync.interval_s)

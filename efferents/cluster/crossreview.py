"""Sibling labs review each other's new journal entries.

A review is one model call from the reviewer lab's perspective (its
hypothesis and latest digest as the lens) about the author's entry and
paper. Spend is charged to the cluster's review ledger, never to the
participant's lab cap. Output is an append-only file under
``shared_journal/reviews/``; only its ``status:`` line may later change,
from ``open`` to ``adopted``.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Callable

from efferents.agents.budget import BudgetExhausted, BudgetTracker
from efferents.agents.model_client import make_client
from efferents.agents.popper_gate import _extract_text
from efferents.agents.state import parse_json_loose
from efferents.cluster.budget import usage_from_response
from efferents.cluster.config import ClusterConfig, ClusterPaths, write_event
from efferents.cluster.edges import citation_edges, reproduction_edges

PROMPT_PATH = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "cross_lab_reviewer.md"
_FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_LENS_CHARS = 4000
_ENTRY_CHARS = 12000


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n\n[... truncated ...]"


def _frontmatter(text: str) -> dict:
    m = _FRONT_RE.match(text)
    out: dict = {}
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip()
    return out


def list_reviews(paths: ClusterPaths) -> list[dict]:
    reviews_dir = paths.shared_journal / "reviews"
    out = []
    if not reviews_dir.is_dir():
        return out
    for path in sorted(reviews_dir.glob("*.md")):
        fm = _frontmatter(path.read_text())
        if fm.get("reviewer_lab") and fm.get("reviewed_lab"):
            out.append({**fm, "path": str(path.relative_to(paths.root))})
    return out


def select_reviewers(entry: dict, labs: list[dict], *, n: int, same_domain_first: bool,
                     existing: list[dict]) -> list[dict]:
    """Deterministic (seeded by the entry hash), never the author, spread out."""
    author = entry["lab_id"]
    counts: dict[str, int] = {}
    for r in existing:
        if r["reviewed_lab"] == author:
            counts[r["reviewer_lab"]] = counts.get(r["reviewer_lab"], 0) + 1
    candidates = [
        lab for lab in labs
        if lab["lab_id"] != author
        and (lab["lab_root"] / "runs.sqlite").exists()
        and counts.get(lab["lab_id"], 0) < 3
    ]
    rng = random.Random(entry.get("sha256") or f"{author}/{entry['campaign_id']}")
    rng.shuffle(candidates)
    if same_domain_first and entry.get("domain"):
        candidates.sort(key=lambda lab: 0 if lab.get("domain") == entry.get("domain") else 1)
    return candidates[:n]


class Reviewer:
    def __init__(self, cfg: ClusterConfig, *, client_factory: Callable | None = None):
        self.cfg = cfg
        self.paths = cfg.paths
        cap = cfg.caps.reviews_total_usd
        self.budget = BudgetTracker(self.paths.reviews_ledger, daily_cap_usd=cap, total_cap_usd=cap)
        self._factory = client_factory or (lambda budget: make_client(budget=budget))
        self.model = cfg.sync.review_model or cfg.model
        self._prompt = PROMPT_PATH.read_text()

    def _lens(self, lab: dict) -> str:
        parts = []
        hyp = lab["submission_dir"] / "hypothesis.md"
        if hyp.is_file():
            parts.append("### Reviewer lab hypothesis\n\n" + _clip(hyp.read_text(), _LENS_CHARS))
        digests = sorted((lab["lab_root"] / "digests").glob("*.md")) if (lab["lab_root"] / "digests").is_dir() else []
        if digests:
            parts.append("### Reviewer lab latest digest\n\n" + _clip(digests[-1].read_text(), _LENS_CHARS))
        return "\n\n".join(parts) or "(the reviewer lab has no digest yet)"

    def _material(self, entry: dict) -> str:
        parts = [f"### Entry from `{entry['lab_id']}` ({entry['campaign_id']})\n\n{entry['body']}"]
        paper = Path(entry["submission_dir"]) / "paper" / f"{entry['campaign_id']}.md"
        if paper.is_file():
            parts.append("### Their paper\n\n" + _clip(paper.read_text(), _ENTRY_CHARS))
        return "\n\n".join(parts)

    def review_entry(self, entry: dict, labs: list[dict]) -> list[dict]:
        existing = list_reviews(self.paths)
        done = {(r["reviewer_lab"], r["campaign_id"]) for r in existing if r["reviewed_lab"] == entry["lab_id"]}
        reviewers = select_reviewers(entry, labs, n=self.cfg.sync.reviewers_per_entry,
                                     same_domain_first=self.cfg.sync.same_domain_first,
                                     existing=existing)
        out = []
        for reviewer in reviewers:
            if (reviewer["lab_id"], entry["campaign_id"]) in done:
                continue
            review = self._one(entry, reviewer)
            if review is not None:
                out.append(review)
        return out

    def _one(self, entry: dict, reviewer: dict) -> dict | None:
        client = self._factory(self.budget)
        system = self._prompt + "\n\n" + self._lens(reviewer)
        messages = [{"role": "user", "content": self._material(entry)}]
        try:
            response = client.messages.create(model=self.model, max_tokens=1500,
                                              system=system, messages=messages)
        except BudgetExhausted:
            write_event(self.paths, "reviews_cap_reached", reviewer=reviewer["lab_id"])
            return None
        except Exception as e:
            write_event(self.paths, "review_failed", reviewer=reviewer["lab_id"],
                        author=entry["lab_id"], detail=f"{type(e).__name__}: {e}"[:300])
            return None
        rec = self.budget.record(agent="crosslab_reviewer", model=self.model,
                                 usage=usage_from_response(response),
                                 notes=f"{reviewer['lab_id']}->{entry['lab_id']}/{entry['campaign_id']}")
        text = _extract_text(response)
        try:
            data = parse_json_loose(text, must_contain='"critique"')
        except json.JSONDecodeError:
            data = {"critique": text.strip()[:1200], "technique": "", "suggestion": "",
                    "headline": "(unstructured review)", "cited_runs": []}
        headline = str(data.get("headline") or "").strip()[:100] or "(no headline)"
        body = (
            f"## Critique\n\n{data.get('critique', '').strip()}\n\n"
            f"## Transferable technique\n\n{data.get('technique', '').strip()}\n\n"
            f"## Suggestion\n\n{data.get('suggestion', '').strip()}\n"
        )
        ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        reviews_dir = self.paths.shared_journal / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        name = f"{reviewer['lab_id']}__{entry['lab_id']}__{entry['campaign_id']}.md"
        path = reviews_dir / name
        cited = data.get("cited_runs") or []
        path.write_text(
            "---\n"
            f"reviewer_lab: {reviewer['lab_id']}\n"
            f"reviewed_lab: {entry['lab_id']}\n"
            f"campaign_id: {entry['campaign_id']}\n"
            f"ts: {ts}\n"
            f"model: {self.model}\n"
            f"cost_usd: {float(rec.get('cost_usd', 0.0)):.4f}\n"
            f"headline: {headline}\n"
            f"cited_runs: {json.dumps(cited)}\n"
            "status: open\n"
            "---\n\n" + body
        )
        with (self.paths.shared_journal / "reviews.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": ts, "reviewer_lab": reviewer["lab_id"],
                                 "reviewed_lab": entry["lab_id"], "campaign_id": entry["campaign_id"],
                                 "headline": headline, "cost_usd": rec.get("cost_usd"),
                                 "path": str(path.relative_to(self.paths.root))}) + "\n")
        return {"reviewer_lab": reviewer["lab_id"], "reviewed_lab": entry["lab_id"],
                "campaign_id": entry["campaign_id"], "headline": headline, "body": body,
                "path": str(path.relative_to(self.paths.root))}


def mark_adopted(paths: ClusterPaths) -> int:
    """Flip ``status: open`` → ``adopted`` when the author later cites or
    reproduces the reviewer's work. Monotone; logged as an event."""
    edges = citation_edges(paths.root) + reproduction_edges(paths.root)
    adopted_pairs = {(e["source"], e["target"]) for e in edges}  # author -> reviewer
    n = 0
    for review in list_reviews(paths):
        if review.get("status") != "open":
            continue
        if (review["reviewed_lab"], review["reviewer_lab"]) in adopted_pairs:
            path = paths.root / review["path"]
            text = path.read_text()
            path.write_text(text.replace("\nstatus: open\n", "\nstatus: adopted\n", 1))
            write_event(paths, "review_adopted", reviewer=review["reviewer_lab"],
                        author=review["reviewed_lab"], campaign_id=review.get("campaign_id"))
            n += 1
    return n

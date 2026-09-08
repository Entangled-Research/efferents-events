"""Network-map edges derived from files a cluster's labs and sync job write.

Every edge is auditable: ``path`` names the file it came from.

  reviewed    shared_journal/reviews/<reviewer>__<author>__<campaign>.md
  cited       labs/<citing>/lab/foundational_deps.jsonl
  reproduced  labs/<reproducer>/paper/reproductions.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REPRO_HEAD_RE = re.compile(r"^## (?P<ts>[^\n]+?) — (?P<lab>[^/\s]+)/(?P<campaign>\S+)", re.MULTILINE)
_REPRO_STATUS_RE = re.compile(r"\*\*Status\*\*:\s*(\w+)")


def _frontmatter(text: str) -> dict:
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            out[k.strip()] = v.strip().strip("'\"")
    return out


def review_edges(cluster_dir: Path) -> list[dict]:
    reviews = Path(cluster_dir) / "shared_journal" / "reviews"
    if not reviews.is_dir():
        return []
    edges = []
    for path in sorted(reviews.glob("*.md")):
        try:
            fm = _frontmatter(path.read_text())
        except OSError:
            continue
        src, dst = fm.get("reviewer_lab"), fm.get("reviewed_lab")
        if not src or not dst or src == dst:
            continue
        edges.append({
            "source": src, "target": dst, "kind": "reviewed",
            "campaign_id": fm.get("campaign_id"), "status": fm.get("status", "open"),
            "ts": fm.get("ts"), "path": str(path.relative_to(cluster_dir)),
        })
    return edges


def citation_edges(cluster_dir: Path) -> list[dict]:
    labs = Path(cluster_dir) / "labs"
    if not labs.is_dir():
        return []
    edges = []
    for lab_dir in sorted(p for p in labs.iterdir() if p.is_dir()):
        deps = lab_dir / "lab" / "foundational_deps.jsonl"
        if not deps.is_file():
            continue
        seen: set[tuple] = set()
        for line in deps.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            target = rec.get("lab_id")
            if not target or target == lab_dir.name:
                continue
            key = (target, rec.get("campaign_id"))
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "source": lab_dir.name, "target": target, "kind": "cited",
                "campaign_id": rec.get("campaign_id"), "ts": rec.get("ts"),
                "path": str(deps.relative_to(cluster_dir)),
            })
    return edges


def reproduction_edges(cluster_dir: Path) -> list[dict]:
    labs = Path(cluster_dir) / "labs"
    if not labs.is_dir():
        return []
    edges = []
    for lab_dir in sorted(p for p in labs.iterdir() if p.is_dir()):
        repro = lab_dir / "paper" / "reproductions.md"
        if not repro.is_file():
            continue
        text = repro.read_text()
        heads = list(_REPRO_HEAD_RE.finditer(text))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            block = text[head.end():end]
            status_m = _REPRO_STATUS_RE.search(block)
            target = head.group("lab")
            if target == lab_dir.name:
                continue
            edges.append({
                "source": lab_dir.name, "target": target, "kind": "reproduced",
                "campaign_id": head.group("campaign"),
                "status": status_m.group(1) if status_m else "pending",
                "ts": head.group("ts").strip(),
                "path": str(repro.relative_to(cluster_dir)),
            })
    return edges


def citation_edges_for(lab_id: str, deps_path: Path) -> list[dict]:
    """Citations one lab reports about itself (for a hub heartbeat)."""
    deps_path = Path(deps_path)
    if not deps_path.is_file():
        return []
    out, seen = [], set()
    for line in deps_path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        target = rec.get("lab_id")
        if not target or target == lab_id or (target, rec.get("campaign_id")) in seen:
            continue
        seen.add((target, rec.get("campaign_id")))
        out.append({"source": lab_id, "target": target, "kind": "cited",
                    "campaign_id": rec.get("campaign_id"), "ts": rec.get("ts")})
    return out


def reproduction_edges_for(lab_id: str, repro_path: Path) -> list[dict]:
    """Reproductions one lab reports about itself (for a hub heartbeat)."""
    repro_path = Path(repro_path)
    if not repro_path.is_file():
        return []
    text = repro_path.read_text()
    heads = list(_REPRO_HEAD_RE.finditer(text))
    out = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        status_m = _REPRO_STATUS_RE.search(text[head.end():end])
        target = head.group("lab")
        if target == lab_id:
            continue
        out.append({"source": lab_id, "target": target, "kind": "reproduced",
                    "campaign_id": head.group("campaign"),
                    "status": status_m.group(1) if status_m else "pending",
                    "ts": head.group("ts").strip()})
    return out


def remote_edges(cluster_dir: Path) -> list[dict]:
    """Edges remote (laptop) labs reported through their heartbeats."""
    root = Path(cluster_dir) / "network" / "labs"
    if not root.is_dir():
        return []
    edges = []
    for lab_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = lab_dir / "edges.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        for kind in ("cited", "reproduced"):
            for e in data.get(kind) or []:
                if not isinstance(e, dict) or not e.get("target") or e["target"] == lab_dir.name:
                    continue
                edges.append({**e, "source": lab_dir.name, "kind": kind,
                              "path": str(path.relative_to(cluster_dir))})
    return edges


def derive_edges(labs: list[dict], cluster_dir: Path) -> list[dict]:
    """Edges between known labs, all kinds, from cluster files."""
    cluster_dir = Path(cluster_dir)
    known = {lab["lab_id"] for lab in labs}
    edges = (review_edges(cluster_dir) + citation_edges(cluster_dir)
             + reproduction_edges(cluster_dir) + remote_edges(cluster_dir))
    return [e for e in edges if e["source"] in known and e["target"] in known]


def edge_summary(edges: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in edges:
        out[e["kind"]] = out.get(e["kind"], 0) + 1
    return out

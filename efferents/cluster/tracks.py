"""Executor tracks: the submission templates participants bind a hypothesis to.

``tracks/<id>/track.yaml`` describes the track for humans and for the
falsifier mapper (knobs, ledger columns, bucket axes); ``tracks/<id>/submission/``
is a complete submission minus ``hypothesis.md``. Both are validated when the
cluster starts so a broken track fails loudly before participants arrive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from efferents.lab import SubmissionError, _build_labconfig

_TRACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STUB_FRONTMATTER = {"falsifiability_gate": "passed", "status": "active", "slug": "track-check"}


class TrackError(ValueError):
    """A track directory violates the template contract."""


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    summary: str
    domain: str | None
    knobs: tuple[dict, ...]
    columns: tuple[dict, ...]
    bucket_axes: tuple[str, ...]
    comparison: dict | None
    example_falsifiers: tuple[dict, ...]
    root: Path
    submission: Path
    lab_yaml: dict = field(default_factory=dict, compare=False)

    def payload(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "domain": self.domain,
            "knobs": list(self.knobs),
            "columns": list(self.columns),
            "bucket_axes": list(self.bucket_axes),
            "comparison": self.comparison,
        }

    def catalogue_text(self) -> str:
        lines = [f"### Track `{self.id}` — {self.title}", self.summary.strip(), ""]
        if self.knobs:
            lines.append("Knobs the experiment runner can vary:")
            for k in self.knobs:
                extra = f" (range {k['range']})" if k.get("range") else ""
                lines.append(f"- `{k['name']}`: {k.get('description', '')}{extra}")
            lines.append("")
        if self.columns:
            lines.append("Metrics reported per run (ledger columns):")
            for c in self.columns:
                direction = f", {c['direction']} is better" if c.get("direction") else ""
                lines.append(f"- `{c['name']}`: {c.get('description', '')}{direction}")
            lines.append("")
        if self.bucket_axes:
            lines.append(f"Bucket axes: {', '.join(self.bucket_axes)}")
        return "\n".join(lines).strip()


def _list_of_named(items, *, key: str, where: str) -> tuple[dict, ...]:
    if items is None:
        return ()
    if not isinstance(items, list):
        raise TrackError(f"{where}: {key} must be a list")
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise TrackError(f"{where}: {key}[{i}] must be a mapping with a name")
        if key == "columns" and not _COL_RE.match(item["name"]):
            raise TrackError(f"{where}: {key}[{i}].name must match [A-Za-z_][A-Za-z0-9_]*")
        out.append(dict(item))
    return tuple(out)


def validate_track(track_dir: Path) -> Track:
    track_dir = Path(track_dir).resolve()
    where = f"tracks/{track_dir.name}"
    meta_path = track_dir / "track.yaml"
    if not meta_path.is_file():
        raise TrackError(f"{where}: track.yaml is missing")
    try:
        meta = yaml.safe_load(meta_path.read_text()) or {}
    except yaml.YAMLError as e:
        raise TrackError(f"{where}: track.yaml: {e}") from e
    if not isinstance(meta, dict):
        raise TrackError(f"{where}: track.yaml must be a mapping")
    track_id = str(meta.get("id") or track_dir.name)
    if not _TRACK_ID_RE.match(track_id):
        raise TrackError(f"{where}: id {track_id!r} is not a valid identifier")
    title = str(meta.get("title") or "").strip()
    summary = str(meta.get("summary") or "").strip()
    if not title or not summary:
        raise TrackError(f"{where}: title and summary are required")

    submission = track_dir / "submission"
    if not (submission / "lab.yaml").is_file():
        raise TrackError(f"{where}: submission/lab.yaml is missing")
    if not (submission / "README.md").is_file():
        raise TrackError(f"{where}: submission/README.md is missing")
    if (submission / "hypothesis.md").exists():
        raise TrackError(f"{where}: submission/ must not ship a hypothesis.md")
    try:
        raw = yaml.safe_load((submission / "lab.yaml").read_text()) or {}
    except yaml.YAMLError as e:
        raise TrackError(f"{where}: submission/lab.yaml: {e}") from e
    if not isinstance(raw, dict):
        raise TrackError(f"{where}: submission/lab.yaml must be a mapping")
    if raw.get("falsifiers"):
        raise TrackError(f"{where}: submission/lab.yaml must not predefine falsifiers")
    try:
        cfg = _build_labconfig(dict(_STUB_FRONTMATTER), raw, submission, check_paths=True)
    except SubmissionError as e:
        raise TrackError(f"{where}: submission/lab.yaml invalid: {e}") from e

    knobs = _list_of_named(meta.get("knobs"), key="knobs", where=where)
    columns = _list_of_named(meta.get("columns"), key="columns", where=where)
    names = {c["name"] for c in columns}
    if columns and cfg.metrics.headline.column not in names:
        raise TrackError(
            f"{where}: headline column {cfg.metrics.headline.column!r} is not listed in columns"
        )
    bucket_axes = tuple(str(b) for b in (meta.get("bucket_axes") or ()))
    if bucket_axes and tuple(bucket_axes) != tuple(cfg.metrics.bucket_axes):
        raise TrackError(
            f"{where}: bucket_axes {list(bucket_axes)} differ from submission/lab.yaml "
            f"metrics.bucket_axes {list(cfg.metrics.bucket_axes)}"
        )
    if not bucket_axes:
        bucket_axes = tuple(cfg.metrics.bucket_axes)
    comparison = meta.get("comparison")
    if comparison is not None and not isinstance(comparison, dict):
        raise TrackError(f"{where}: comparison must be a mapping")
    examples = meta.get("example_falsifiers") or ()
    if not isinstance(examples, list):
        raise TrackError(f"{where}: example_falsifiers must be a list")
    return Track(
        id=track_id,
        title=title,
        summary=summary,
        domain=str(meta["domain"]) if meta.get("domain") else (raw.get("domain") or None),
        knobs=knobs,
        columns=columns,
        bucket_axes=bucket_axes,
        comparison=comparison,
        example_falsifiers=tuple(dict(e) for e in examples),
        root=track_dir,
        submission=submission,
        lab_yaml=raw,
    )


def load_tracks(tracks_dir: Path) -> dict[str, Track]:
    tracks_dir = Path(tracks_dir)
    if not tracks_dir.is_dir():
        raise TrackError(f"tracks directory {tracks_dir} does not exist")
    tracks: dict[str, Track] = {}
    for child in sorted(p for p in tracks_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        track = validate_track(child)
        if track.id in tracks:
            raise TrackError(f"duplicate track id {track.id!r}")
        tracks[track.id] = track
    return tracks


def catalogue_text(tracks: dict[str, Track]) -> str:
    if not tracks:
        return ""
    head = (
        "## Available experiment tracks (orientation only)\n\n"
        "After the gate passes the human will pick one of these executors and the\n"
        "falsifier will be mapped onto its per-run metric columns. Use them to\n"
        "steer quantities toward what can actually be measured; do not restrict\n"
        "the human's creativity to them.\n"
    )
    return head + "\n\n".join(t.catalogue_text() for t in tracks.values())

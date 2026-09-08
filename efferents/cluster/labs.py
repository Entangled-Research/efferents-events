"""Create a participant's lab from a track template and an approved hypothesis."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from efferents.agents.popper_gate import frontmatter_value, write_charter
from efferents.cli import _init_lab_root
from efferents.cluster.config import ClusterConfig, write_event
from efferents.cluster.owners import Owner
from efferents.cluster.tracks import Track
from efferents.dashboard.control import (
    OWNER_FILENAME,
    ConnectedLab,
    ControlError,
    connected_lab_from_record,
)
from efferents.lab import LabConfig, SubmissionError
from efferents.registry import LabRecord, Registry

_LAB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IGNORE = shutil.ignore_patterns(
    "lab", ".git", "__pycache__", "*.pyc", ".env", "popper-corpus", ".venv", "paper",
)
_creation_lock = threading.Lock()


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-.")
    value = re.sub(r"-{2,}", "-", value)
    return value[:100] or "lab"


def derive_lab_id(preferred: str, taken: set[str]) -> str:
    base = slugify(preferred)
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base[:120]}-{n}"
        if candidate not in taken:
            return candidate
    raise ControlError("Could not find a free lab id.", status=409)


def taken_lab_ids(cfg: ClusterConfig) -> set[str]:
    ids = {r.lab_id for r in Registry().list()}
    if cfg.paths.labs.is_dir():
        ids |= {p.name for p in cfg.paths.labs.iterdir() if p.is_dir()}
    return ids


def create_lab(
    cfg: ClusterConfig,
    *,
    track: Track,
    owner: Owner,
    hypothesis_text: str,
    first_claim: str,
    lab_id: str | None,
    falsifiers: list[dict] | None,
    design_notes: str = "",
    session_id: str | None = None,
) -> ConnectedLab:
    """Materialise ``labs/<lab_id>/`` and register it (stopped).

    Rolls the directory back on any failure so a half-built lab never lingers.
    """
    slug = frontmatter_value(hypothesis_text, "slug") or "hypothesis"
    with _creation_lock:
        taken = taken_lab_ids(cfg)
        if lab_id:
            lab_id = lab_id.strip()
            if not _LAB_ID_RE.match(lab_id):
                raise ControlError(
                    "Lab ids start with a letter or digit and use only letters, digits, "
                    "'.', '_' and '-'."
                )
            if lab_id in taken:
                raise ControlError(f"Lab id {lab_id!r} is taken.", status=409)
        else:
            lab_id = derive_lab_id(slug, taken)
        if len(owner.labs) >= cfg.labs.max_per_owner:
            raise ControlError(
                f"You already own {len(owner.labs)} lab(s); the limit is "
                f"{cfg.labs.max_per_owner}.", status=409,
            )
        dest = cfg.paths.labs / lab_id
        if dest.exists():
            raise ControlError(f"Lab id {lab_id!r} is taken.", status=409)
        try:
            return _materialise(
                cfg, dest=dest, lab_id=lab_id, slug=slug, track=track, owner=owner,
                hypothesis_text=hypothesis_text, first_claim=first_claim,
                falsifiers=falsifiers, design_notes=design_notes, session_id=session_id,
            )
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise


def _materialise(
    cfg: ClusterConfig, *, dest: Path, lab_id: str, slug: str, track: Track, owner: Owner,
    hypothesis_text: str, first_claim: str, falsifiers: list[dict] | None,
    design_notes: str, session_id: str | None,
) -> ConnectedLab:
    shutil.copytree(track.submission, dest, ignore=_IGNORE)
    (dest / "hypothesis.md").write_text(hypothesis_text)
    corpus = dest / "popper-corpus" / slug
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "hypothesis.md").write_text(hypothesis_text)

    raw = yaml.safe_load((dest / "lab.yaml").read_text()) or {}
    raw["lab_id"] = lab_id
    if track.domain:
        raw["domain"] = track.domain
    cap = float(cfg.labs.total_cap_usd)
    raw["budget"] = {
        **(raw.get("budget") or {}),
        # Daily == lifetime: the lifetime path halts cleanly instead of
        # sleeping until the next UTC day.
        "daily_cap_usd": cap,
        "total_cap_usd": cap,
        "sonnet_default": True,
    }
    if cfg.cadence_raw:
        raw["cadence"] = dict(cfg.cadence_raw)
    if falsifiers:
        raw["falsifiers"] = [dict(f) for f in falsifiers]
    else:
        raw.pop("falsifiers", None)
    autonomy = dict(raw.get("autonomy") or {})
    autonomy["coder_enabled"] = False  # no source mutation on a shared host
    raw["autonomy"] = autonomy
    (dest / "lab.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))

    try:
        lab_cfg = LabConfig.from_submission(dest)
    except SubmissionError as e:
        raise ControlError(f"The generated lab did not validate: {e}", status=422) from e

    digest = "sha256:" + hashlib.sha256(hypothesis_text.encode()).hexdigest()
    notes = design_notes.strip()
    write_charter(
        dest / "context",
        initial_direction=first_claim or "(no verbatim claim recorded)",
        prompted_by=f"participant:{owner.name}",
        hypothesis_path="hypothesis.md",
        hypothesis_hash=digest,
        design_notes=notes,
        title=f"event intake: {slug}",
    )
    lab_root = dest / "lab"
    _init_lab_root(dest, lab_root, cfg=lab_cfg)
    (dest / OWNER_FILENAME).write_text(json.dumps({
        "owner_id": owner.owner_id,
        "owner_name": owner.name,
        "track": track.id,
        "intake_session": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))
    record = LabRecord(
        lab_id=lab_id,
        submission_dir=str(dest),
        lab_root=str(lab_root),
        pid=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        status="stopped",
    )
    Registry().register(record)
    write_event(cfg.paths, "lab_created", owner_id=owner.owner_id, lab_id=lab_id,
                track=track.id, session_id=session_id)
    return connected_lab_from_record(record, lab_cfg)

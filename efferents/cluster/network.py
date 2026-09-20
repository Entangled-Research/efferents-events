"""The hub side of the terminal path: remote labs that run on participants'
laptops and talk to this server over HTTP.

State per remote lab lives under ``network/labs/<lab_id>/``:
``registration.json`` (owner, domain, track, hypothesis hash),
``hypothesis.md``, ``heartbeat.json`` (latest status), ``edges.json``
(citations/reproductions the daemon reported), ``paper/journal.md`` and
``paper/<campaign>.md`` (pushed by the daemon), ``paper/incoming_reviews.md``
(written by the sync job, pulled by the daemon).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from efferents.agents import federation
from efferents.cluster.config import ClusterConfig, control_flag, is_frozen, write_event
from efferents.cluster.owners import Owner
from efferents.cluster.tracks import Track
from efferents.dashboard.control import ControlError

_LAB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAMPAIGN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_TEXT = 200_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


class NetworkHub:
    def __init__(self, cfg: ClusterConfig, tracks: dict[str, Track]):
        self.cfg = cfg
        self.paths = cfg.paths
        self.tracks = tracks
        self.root = cfg.paths.root / "network" / "labs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # --- helpers -------------------------------------------------------------------

    def lab_dir(self, lab_id: str) -> Path:
        if not _LAB_ID_RE.match(lab_id or ""):
            raise ControlError("Invalid lab id.", status=400)
        return self.root / lab_id

    def registration(self, lab_id: str) -> dict:
        reg = _read_json(self.lab_dir(lab_id) / "registration.json")
        if not reg:
            raise ControlError(f"Unknown network lab {lab_id!r}.", status=404)
        return reg

    def require_owner(self, owner: Owner, lab_id: str) -> dict:
        reg = self.registration(lab_id)
        if reg.get("owner_id") != owner.owner_id:
            raise ControlError("Only this lab's owner can report for it.", status=403)
        return reg

    def public_url(self, fallback: str) -> str:
        return (self.cfg.public_url or fallback).rstrip("/")

    # --- config for the participant's agent ------------------------------------

    def config_payload(self, owner: Owner, base_url: str) -> dict:
        url = self.public_url(base_url)
        azure_enabled = bool(os.environ.get("EFFERENTS_AZURE_OPENAI_ENDPOINT"))
        if azure_enabled:
            model_env = {
                "OPENAI_API_KEY": owner.token,
                "EFFERENTS_API_BASE": f"{url}/proxy/openai/v1",
                "EFFERENTS_MODEL": "openai/gpt-5.6-luna",
                "EFFERENTS_MODEL_LIBRARIAN": "openai/gpt-5.6-luna",
                "EFFERENTS_MODEL_REVIEWER": "openai/gpt-5.6-luna",
                "EFFERENTS_MODEL_REBUTTAL": "openai/gpt-4.1-nano",
                "EFFERENTS_MODEL_SUPERVISOR": "openai/gpt-5.6-sol",
                "EFFERENTS_MODEL_ANALYST": "openai/gpt-5.6-sol",
                "EFFERENTS_MODEL_CODER": "openai/gpt-5.6-sol",
            }
        else:
            model_env = {
                "ANTHROPIC_API_KEY": owner.token,
                "ANTHROPIC_BASE_URL": f"{url}/proxy/anthropic",
            }
        return {
            "hub_url": url,
            "owner": owner.public(),
            "install": {
                "repo_url": self.cfg.network.repo_url,
                "ref": self.cfg.network.install_ref,
                "pip_spec": f"git+{self.cfg.network.repo_url}.git@{self.cfg.network.install_ref}",
            },
            "env": {
                **model_env,
                "EFFERENTS_NETWORK_URL": url,
                "EFFERENTS_NETWORK_TOKEN": owner.token,
                "OMP_NUM_THREADS": "1",
            },
            "lab_yaml": {
                "budget": {"daily_cap_usd": self.cfg.labs.total_cap_usd,
                           "total_cap_usd": self.cfg.labs.total_cap_usd,
                           "sonnet_default": True},
                "cadence": dict(self.cfg.cadence_raw),
                "autonomy": {"coder_enabled": False},
            },
            "limits": {"labs_per_owner": self.cfg.labs.max_per_owner,
                       "proxy_cap_usd": self.cfg.proxy.cap_per_owner_usd},
            "tracks": [t.payload() for t in self.tracks.values()],
            "frozen": is_frozen(self.paths),
        }

    def track_tarball(self, track_id: str) -> bytes:
        track = self.tracks.get(track_id or "")
        if track is None:
            raise ControlError("Unknown track.", status=404)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(track.root / "track.yaml", arcname=f"{track.id}/track.yaml")
            for path in sorted(track.submission.rglob("*")):
                rel = path.relative_to(track.submission)
                if any(part in ("__pycache__", ".git", "lab", ".venv") for part in rel.parts):
                    continue
                if path.suffix == ".pyc":
                    continue
                tar.add(path, arcname=f"{track.id}/submission/{rel}", recursive=False)
        return buf.getvalue()

    # --- registration and heartbeat ---------------------------------------------

    def register(self, owner: Owner, payload: dict) -> dict:
        lab_id = str(payload.get("lab_id") or "").strip()
        if not _LAB_ID_RE.match(lab_id):
            raise ControlError("lab_id must start with a letter or digit and use only "
                               "letters, digits, '.', '_' and '-'.")
        hypothesis = str(payload.get("hypothesis") or "")
        if not hypothesis.strip() or len(hypothesis) > _MAX_TEXT:
            raise ControlError("Send the gated hypothesis.md text (non-empty, under 200 kB).")
        if "falsifiability_gate: passed" not in hypothesis:
            raise ControlError("Only a hypothesis with falsifiability_gate: passed can register.",
                               status=422)
        if is_frozen(self.paths):
            raise ControlError("The event budget is frozen; no new labs.", status=409)
        with self._lock:
            d = self.lab_dir(lab_id)
            existing = _read_json(d / "registration.json")
            if existing and existing.get("owner_id") != owner.owner_id:
                raise ControlError(f"Lab id {lab_id!r} is taken by another participant.", status=409)
            owned = [p.name for p in self.root.iterdir()
                     if p.is_dir() and _read_json(p / "registration.json").get("owner_id") == owner.owner_id]
            if not existing and len(owned) >= self.cfg.labs.max_per_owner:
                raise ControlError(f"You already registered {len(owned)} lab(s); the limit is "
                                   f"{self.cfg.labs.max_per_owner}.", status=409)
            reg = {
                "lab_id": lab_id,
                "owner_id": owner.owner_id,
                "owner_name": owner.name,
                "domain": str(payload.get("domain") or "unspecified")[:120],
                "track": (str(payload.get("track"))[:64] if payload.get("track") else None),
                "hypothesis_hash": "sha256:" + hashlib.sha256(hypothesis.encode()).hexdigest(),
                "host": str(payload.get("host") or "")[:120],
                "registered_at": existing.get("registered_at") or _now(),
                "updated_at": _now(),
                "remote": True,
            }
            d.mkdir(parents=True, exist_ok=True)
            (d / "hypothesis.md").write_text(hypothesis)
            (d / "paper").mkdir(exist_ok=True)
            _write_json(d / "registration.json", reg)
        write_event(self.paths, "network_register", owner_id=owner.owner_id, lab_id=lab_id,
                    track=reg["track"], renewed=bool(existing))
        return {"registered": True, "lab_id": lab_id, "heartbeat_s": self.cfg.network.heartbeat_s,
                "pull_s": self.cfg.network.pull_s}

    def heartbeat(self, owner: Owner, lab_id: str, payload: dict) -> dict:
        self.require_owner(owner, lab_id)
        d = self.lab_dir(lab_id)
        beat = {
            "ts": _now(),
            "status": str(payload.get("status") or "running")[:16],
            "runs": int(payload.get("runs") or 0),
            "spend_usd": float(payload.get("spend_usd") or 0.0),
            "cap_usd": payload.get("cap_usd"),
            "headline": payload.get("headline") if isinstance(payload.get("headline"), dict) else {},
            "hypothesis": payload.get("hypothesis") if isinstance(payload.get("hypothesis"), dict) else {},
            "verdict": payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {},
            "papers": int(payload.get("papers") or 0),
            "last_activity": payload.get("last_activity"),
            "halt_reason": (str(payload.get("halt_reason"))[:200] if payload.get("halt_reason") else None),
        }
        _write_json(d / "heartbeat.json", beat)
        edges = payload.get("edges")
        if isinstance(edges, dict):
            _write_json(d / "edges.json", {
                "cited": [e for e in (edges.get("cited") or []) if isinstance(e, dict)][:200],
                "reproduced": [e for e in (edges.get("reproduced") or []) if isinstance(e, dict)][:200],
            })
        return {
            "ok": True,
            "pause": control_flag(self.paths, "pause_all") or is_frozen(self.paths)
            or control_flag(self.paths, f"halt_{lab_id}"),
            "frozen": is_frozen(self.paths),
            "message": self._message_for(lab_id),
        }

    def _message_for(self, lab_id: str) -> str | None:
        if is_frozen(self.paths):
            return "The event budget is frozen; the hub asked every lab to pause."
        if control_flag(self.paths, "pause_all"):
            return "The organizer paused every lab."
        if control_flag(self.paths, f"halt_{lab_id}"):
            return "The organizer paused this lab."
        return None

    # --- journal push and pulls --------------------------------------------------

    def push_journal(self, owner: Owner, lab_id: str, payload: dict) -> dict:
        self.require_owner(owner, lab_id)
        d = self.lab_dir(lab_id) / "paper"
        d.mkdir(parents=True, exist_ok=True)
        journal_text = str(payload.get("journal") or "")
        if len(journal_text) > _MAX_TEXT:
            raise ControlError("Journal too large.", status=413)
        added = 0
        if journal_text.strip():
            entries = federation.parse_journal_entries(journal_text)
            for e in entries:
                if not e.get("lab_id"):
                    e["lab_id"] = lab_id
            path = d / "journal.md"
            if not path.exists():
                path.write_text("# Journal (pushed from the lab)\n\n<!-- ENTRIES BELOW -->\n")
            known = {(x.get("lab_id"), x["campaign_id"]) for x in
                     federation.parse_journal_entries(path.read_text())}
            content = path.read_text()
            for e in entries:
                if (e["lab_id"], e["campaign_id"]) in known:
                    continue
                body = e["body"].rstrip()
                if "**Lab**:" not in body:
                    head, _, rest = body.partition("\n")
                    body = f"{head}\n**Lab**: {lab_id}\n{rest}".rstrip()
                marker = content.index("<!-- ENTRIES BELOW -->") + len("<!-- ENTRIES BELOW -->")
                content = content[:marker] + "\n\n" + body + "\n" + content[marker:]
                added += 1
            path.write_text(content)
        papers = payload.get("papers") or {}
        stored = 0
        if isinstance(papers, dict):
            for cid, text in list(papers.items())[:20]:
                if not _CAMPAIGN_RE.match(str(cid)) or not isinstance(text, str):
                    continue
                target = d / f"{cid}.md"
                if not target.exists() and len(text) <= _MAX_TEXT:
                    target.write_text(text)
                    stored += 1
        if added or stored:
            write_event(self.paths, "network_push", owner_id=owner.owner_id, lab_id=lab_id,
                        entries=added, papers=stored)
        return {"ok": True, "entries_added": added, "papers_stored": stored}

    def feed(self) -> str:
        hub = self.paths.shared_journal / "journal.md"
        return hub.read_text() if hub.is_file() else ""

    def reviews_for(self, owner: Owner, lab_id: str) -> str:
        self.require_owner(owner, lab_id)
        path = self.lab_dir(lab_id) / "paper" / "incoming_reviews.md"
        return path.read_text() if path.is_file() else ""

    # --- reads for the dashboard -------------------------------------------------

    def list_labs(self) -> list[dict]:
        out = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            reg = _read_json(d / "registration.json")
            if not reg:
                continue
            beat = _read_json(d / "heartbeat.json")
            out.append({"registration": reg, "heartbeat": beat, "dir": d})
        return out

    def _status(self, beat: dict) -> str:
        if not beat:
            return "registered"
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat["ts"])).total_seconds()
        except (KeyError, ValueError):
            return "stale"
        if age > self.cfg.network.stale_after_s:
            return "stale"
        return beat.get("status") or "running"

    def portfolio_rows(self) -> list[dict]:
        rows = []
        for lab in self.list_labs():
            reg, beat = lab["registration"], lab["heartbeat"]
            papers = len([p for p in (lab["dir"] / "paper").glob("*.md")
                          if p.name not in ("journal.md", "incoming_reviews.md")]) \
                if (lab["dir"] / "paper").is_dir() else 0
            rows.append({
                "lab_id": reg["lab_id"],
                "domain": reg.get("domain"),
                "subdomain": None,
                "pi_handle": None,
                "repository": None,
                "submission_dir": None,
                "owner_id": reg.get("owner_id"),
                "owner_name": reg.get("owner_name"),
                "track": reg.get("track"),
                "visibility": "private",
                "remote": True,
                "host": reg.get("host"),
                "status": self._status(beat),
                "budget": {"spent": float(beat.get("spend_usd") or 0.0),
                           "cap": float(beat.get("cap_usd") or self.cfg.labs.total_cap_usd)},
                "headline": beat.get("headline") or {"column": "metric", "direction": "min",
                                                     "best": None, "latest": None, "observations": 0},
                "papers": max(papers, int(beat.get("papers") or 0)),
                "last_activity": beat.get("last_activity") or beat.get("ts"),
                "hypothesis": beat.get("hypothesis") or {"question": "", "claim": "", "falsifier": "", "student": ""},
                "verdict": beat.get("verdict") or {"status": "undecided", "line": "verdict: undecided"},
                "heartbeat_ts": beat.get("ts"),
                "halt_reason": beat.get("halt_reason"),
            })
        return rows

    def lab_view(self, lab_id: str, kind: str) -> Any:
        """Read-only views of a remote lab for the observer panel."""
        reg = self.registration(lab_id)
        d = self.lab_dir(lab_id)
        beat = _read_json(d / "heartbeat.json")
        if kind == "control":
            return {
                "connected": True, "lab_id": lab_id, "domain": reg.get("domain"),
                "submission_dir": None, "lab_root": None, "source": reg.get("host") or "remote lab",
                "repository": None, "readme_path": None, "status": self._status(beat),
                "owner_paused": (beat.get("status") == "paused"), "owner_id": reg.get("owner_id"),
                "owner_name": reg.get("owner_name"), "track": reg.get("track"), "remote": True,
                "has_api_key": True, "paused_demo": False, "modes": [], "steering": [],
                "contract": {"readme": False, "lab_yaml": True, "hypothesis": True},
            }
        if kind == "state":
            return {"lab_id": lab_id, "domain": reg.get("domain"), "status": self._status(beat),
                    "budget": {"spent": float(beat.get("spend_usd") or 0.0),
                               "cap": float(beat.get("cap_usd") or self.cfg.labs.total_cap_usd)},
                    "hypothesis": beat.get("hypothesis") or {"question": "", "claim": "", "falsifier": "", "student": ""}}
        if kind == "runs":
            head = beat.get("headline") or {}
            return {"headline": {"column": head.get("column", "metric"), "direction": head.get("direction", "min")},
                    "runs": [], "series": [],
                    "history": {"total": int(beat.get("runs") or 0), "best": head.get("best"), "best_run_id": None}}
        if kind == "papers":
            from efferents.dashboard.reader import read_papers  # noqa: PLC0415
            fake_root = d / "lab"  # read_papers scans <root>.parent/paper
            return read_papers(fake_root)
        if kind == "activity":
            journal = d / "paper" / "journal.md"
            entries = federation.parse_journal_entries(journal.read_text()) if journal.is_file() else []
            return [{"timestamp": e["ts"], "title": f"paper accepted: {e['campaign_id']}",
                     "body": e.get("headline") or ""} for e in entries[:20]]
        if kind == "evidence":
            return {"panels": [], "constraints": [], "comparison": {"axis": None, "labels": {}, "order": []},
                    "records": [], "artifact_count": 0}
        if kind == "verdict":
            v = beat.get("verdict") or {}
            return {"verdict": v.get("status", "undecided"), "line": v.get("line", "verdict: undecided"),
                    "n_runs": int(beat.get("runs") or 0), "axes": [], "comparison": {"axis": None, "labels": {}},
                    "columns": [], "buckets": [], "paired": [], "falsifiers": []}
        raise ControlError("Unknown lab view.", status=404)

    def sync_labs(self) -> list[dict]:
        """Lab dicts in the shape efferents.cluster.sync expects."""
        out = []
        for lab in self.list_labs():
            reg, beat = lab["registration"], lab["heartbeat"]
            out.append({"lab_id": reg["lab_id"], "submission_dir": lab["dir"],
                        "lab_root": lab["dir"] / "lab", "domain": reg.get("domain"),
                        "running": self._status(beat) in ("running", "paused"),
                        "remote": True, "runs": int(beat.get("runs") or 0)})
        return out

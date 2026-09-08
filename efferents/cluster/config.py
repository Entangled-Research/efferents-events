"""cluster.yaml loader, on-disk layout, and small file-backed controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from efferents.lab import Cadence, SubmissionError, _parse_cadence


class ClusterConfigError(ValueError):
    """cluster.yaml is missing, malformed, or inconsistent."""


CONFIG_FILENAME = "cluster.yaml"
ENV_FILENAME = ".env"
OWNERS_FILENAME = "owners.json"
EVENTS_FILENAME = "events.jsonl"
STATUS_FILENAME = "status.json"
RESTARTS_FILENAME = "restarts.jsonl"

# Daemon credentials that must not travel from the server into daemons that
# would fan them out as notifications (one push per lab per event).
_DAEMON_ENV_STRIP = ("NTFY_TOPIC",)


@dataclass(frozen=True)
class ClusterPaths:
    root: Path

    @property
    def config(self) -> Path: return self.root / CONFIG_FILENAME
    @property
    def env(self) -> Path: return self.root / ENV_FILENAME
    @property
    def home(self) -> Path: return self.root / "home"
    @property
    def labs(self) -> Path: return self.root / "labs"
    @property
    def intake(self) -> Path: return self.root / "intake"
    @property
    def owners(self) -> Path: return self.root / OWNERS_FILENAME
    @property
    def shared_journal(self) -> Path: return self.root / "shared_journal"
    @property
    def controls(self) -> Path: return self.root / "controls"
    @property
    def events(self) -> Path: return self.root / EVENTS_FILENAME
    @property
    def status(self) -> Path: return self.root / STATUS_FILENAME
    @property
    def restarts(self) -> Path: return self.root / RESTARTS_FILENAME
    @property
    def intake_ledger(self) -> Path: return self.intake / "budget.jsonl"
    @property
    def reviews_ledger(self) -> Path: return self.shared_journal / "ledger.jsonl"

    def tracks(self, tracks_dir: str) -> Path:
        candidate = Path(tracks_dir)
        return candidate if candidate.is_absolute() else self.root / candidate

    def ensure(self) -> None:
        for d in (self.home, self.labs, self.intake, self.shared_journal, self.controls):
            d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class IntakeLimits:
    cap_per_owner_usd: float = 1.0
    cap_total_usd: float = 5.0
    max_turns: int = 40
    max_sessions_per_owner: int = 3
    max_tokens: int = 2048
    message_max_chars: int = 4000


@dataclass(frozen=True)
class LabPolicy:
    total_cap_usd: float = 3.0
    max_per_owner: int = 2
    auto_start: bool = True


@dataclass(frozen=True)
class Caps:
    cluster_total_usd: float = 20.0
    reviews_total_usd: float = 3.0
    warn_at_fraction: float = 0.8


@dataclass(frozen=True)
class Supervision:
    tick_s: float = 30.0
    max_restarts_per_lab: int = 3
    restart_window_min: float = 30.0
    start_stagger_s: float = 3.0
    max_starts_per_tick: int = 5
    log_rotate_mb: float = 20.0
    min_free_disk_gb: float = 3.0


@dataclass(frozen=True)
class SyncPolicy:
    interval_s: float = 120.0
    reviewers_per_entry: int = 2
    same_domain_first: bool = True
    max_reviews_per_tick: int = 10
    review_model: str | None = None  # None → cluster.model


@dataclass(frozen=True)
class SessionPolicy:
    max_age_hours: float = 12.0
    secure_cookies: bool = True
    trust_proxy: bool = True


@dataclass(frozen=True)
class ClusterConfig:
    name: str
    join_code: str
    paths: ClusterPaths
    tracks_dir: str = "tracks"
    model: str = "claude-sonnet-4-6"
    intake: IntakeLimits = field(default_factory=IntakeLimits)
    labs: LabPolicy = field(default_factory=LabPolicy)
    caps: Caps = field(default_factory=Caps)
    cadence: Cadence = field(default_factory=Cadence)
    cadence_raw: dict = field(default_factory=dict)
    supervision: Supervision = field(default_factory=Supervision)
    sync: SyncPolicy = field(default_factory=SyncPolicy)
    session: SessionPolicy = field(default_factory=SessionPolicy)

    @property
    def tracks_path(self) -> Path:
        return self.paths.tracks(self.tracks_dir)


def _section(raw: dict, key: str, cls, *, where: str):
    block = raw.get(key) or {}
    if not isinstance(block, dict):
        raise ClusterConfigError(f"{where}: {key} must be a mapping")
    fields = cls.__dataclass_fields__
    unknown = set(block) - set(fields)
    if unknown:
        raise ClusterConfigError(f"{where}: {key} has unknown keys {sorted(unknown)}")
    values = {}
    for name, value in block.items():
        target = fields[name].type
        try:
            if target in ("int", int):
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError
                values[name] = int(value)
            elif target in ("float", float):
                values[name] = float(value)
            elif target in ("bool", bool):
                if not isinstance(value, bool):
                    raise ValueError
                values[name] = value
            else:
                values[name] = value
        except (TypeError, ValueError) as e:
            raise ClusterConfigError(f"{where}: {key}.{name} has the wrong type") from e
        if isinstance(values[name], (int, float)) and not isinstance(values[name], bool) \
                and values[name] < 0:
            raise ClusterConfigError(f"{where}: {key}.{name} must be non-negative")
    return cls(**values)


def load_cluster_config(root: str | Path) -> ClusterConfig:
    paths = ClusterPaths(Path(root).resolve())
    if not paths.config.is_file():
        raise ClusterConfigError(f"{paths.config} not found (run `efferents cluster init`)")
    try:
        raw = yaml.safe_load(paths.config.read_text()) or {}
    except yaml.YAMLError as e:
        raise ClusterConfigError(f"{paths.config}: {e}") from e
    if not isinstance(raw, dict):
        raise ClusterConfigError(f"{paths.config}: top level must be a mapping")
    where = CONFIG_FILENAME
    name = str(raw.get("name") or "").strip()
    join_code = str(raw.get("join_code") or "").strip()
    if not name:
        raise ClusterConfigError(f"{where}: name is required")
    if len(join_code) < 4:
        raise ClusterConfigError(f"{where}: join_code must be at least 4 characters")
    try:
        cadence = _parse_cadence(raw.get("cadence"))
    except SubmissionError as e:
        raise ClusterConfigError(f"{where}: {e}") from e
    cfg = ClusterConfig(
        name=name,
        join_code=join_code,
        paths=paths,
        tracks_dir=str(raw.get("tracks_dir") or "tracks"),
        model=str(raw.get("model") or "claude-sonnet-4-6"),
        intake=_section(raw, "intake", IntakeLimits, where=where),
        labs=_section(raw, "labs", LabPolicy, where=where),
        caps=_section(raw, "caps", Caps, where=where),
        cadence=cadence,
        cadence_raw=dict(raw.get("cadence") or {}),
        supervision=_section(raw, "supervision", Supervision, where=where),
        sync=_section(raw, "sync", SyncPolicy, where=where),
        session=_section(raw, "session", SessionPolicy, where=where),
    )
    if cfg.labs.total_cap_usd <= 0:
        raise ClusterConfigError(f"{where}: labs.total_cap_usd must be positive")
    if not 0 < cfg.caps.warn_at_fraction <= 1:
        raise ClusterConfigError(f"{where}: caps.warn_at_fraction must be in (0, 1]")
    return cfg


DEFAULT_CONFIG = """\
# efferents cluster — policy only. Secrets live in .env (mode 0600).
name: "Research lab night"
join_code: "change-me"
tracks_dir: tracks
model: "claude-sonnet-4-6"          # intake dialogue, falsifier binding, cross-lab reviews

intake:
  cap_per_owner_usd: 1.0
  cap_total_usd: 5.0
  max_turns: 40
  max_sessions_per_owner: 3
  max_tokens: 2048
  message_max_chars: 4000

labs:
  total_cap_usd: 3.0                # per lab; also its daily cap so the lifetime halt wins
  max_per_owner: 2
  auto_start: true

caps:
  cluster_total_usd: 20.0           # intake + every lab ledger + reviews; freeze at this.
                                    # Rehearsal value. A 50-lab event needs ~650.
  reviews_total_usd: 3.0
  warn_at_fraction: 0.8

cadence:                            # written into every lab.yaml at creation
  runs_per_digest: 3
  hours_per_digest: 0.1667
  min_runs_for_digest: 1
  runs_per_paper: 5
  hours_per_paper: 0.5
  empty_queue_sleep_s: 20
  step_pause_s: 20
  researcher_min_interval_s: 360
  stall_hours: 0.25
  backoff_cap_s: 300

supervision:
  tick_s: 30
  max_restarts_per_lab: 3
  restart_window_min: 30
  start_stagger_s: 3
  max_starts_per_tick: 5
  log_rotate_mb: 20
  min_free_disk_gb: 3

sync:
  interval_s: 120
  reviewers_per_entry: 2
  same_domain_first: true
  max_reviews_per_tick: 10

session:
  max_age_hours: 12
  secure_cookies: true              # set false only for plain-http rehearsals
  trust_proxy: true                 # X-Forwarded-For from the reverse proxy
"""

DEFAULT_ENV = """\
# Organizer credentials for the cluster server and every daemon it starts.
# Loaded into the server environment only; never shown to participants.
ANTHROPIC_API_KEY=
# EFFERENTS_REVIEW_API_KEY=            # optional second key for cross-lab reviews
# OPENAI_API_KEY=                      # optional spillover provider
# EFFERENTS_MODEL=claude-sonnet-4-6,openai/gpt-4.1
# EFFERENTS_MODEL_SUPERVISOR=claude-sonnet-4-6
# EFFERENTS_MODEL_ANALYST=claude-sonnet-4-6
# EFFERENTS_MAX_CONCURRENT_CALLS=12
# EFFERENTS_ANTHROPIC_MAX_RETRIES=4
# POPPER_PROBE_REPO=/srv/efferents/popper-probe
# NTFY_TOPIC=                          # keeper notifications only; stripped from daemons
OMP_NUM_THREADS=1
"""


def init_cluster(root: str | Path) -> list[Path]:
    """Create the cluster skeleton. Never overwrites an existing file."""
    paths = ClusterPaths(Path(root).resolve())
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.ensure()
    paths.tracks("tracks").mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if not paths.config.exists():
        paths.config.write_text(DEFAULT_CONFIG)
        written.append(paths.config)
    if not paths.env.exists():
        paths.env.write_text(DEFAULT_ENV)
        os.chmod(paths.env, 0o600)
        written.append(paths.env)
    return written


def daemon_env(cfg: ClusterConfig, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for daemons and CLI children started by cluster processes."""
    env = {k: v for k, v in os.environ.items() if k not in _DAEMON_ENV_STRIP}
    env["EFFERENTS_HOME"] = str(cfg.paths.home)
    env["EFFERENTS_CLUSTER_DIR"] = str(cfg.paths.root)
    if extra:
        env.update(extra)
    return env


def activate_environment(cfg: ClusterConfig) -> None:
    """Point this process at the cluster: registry home, cluster dir, .env keys.

    Must run before any ``Registry()`` is constructed.
    """
    from efferents.envfile import load_dotenv  # noqa: PLC0415
    load_dotenv(cfg.paths.env)
    os.environ["EFFERENTS_HOME"] = str(cfg.paths.home)
    os.environ["EFFERENTS_CLUSTER_DIR"] = str(cfg.paths.root)
    if cfg.model and not os.environ.get("EFFERENTS_MODEL"):
        os.environ["EFFERENTS_MODEL"] = cfg.model
    cfg.paths.ensure()


def write_event(paths: ClusterPaths, event: str, **fields: Any) -> dict:
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    paths.root.mkdir(parents=True, exist_ok=True)
    with paths.events.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def control_flag(paths: ClusterPaths, name: str) -> bool:
    return (paths.controls / name).exists()


def set_control_flag(paths: ClusterPaths, name: str, reason: str = "") -> Path:
    paths.controls.mkdir(parents=True, exist_ok=True)
    flag = paths.controls / name
    if not flag.exists():
        flag.write_text(
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {reason}\n"
        )
    return flag


def clear_control_flag(paths: ClusterPaths, name: str) -> None:
    flag = paths.controls / name
    if flag.exists():
        flag.unlink()


def is_frozen(paths: ClusterPaths) -> bool:
    return control_flag(paths, "frozen")

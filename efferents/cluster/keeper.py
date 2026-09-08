"""Cluster keeper: supervise many daemons on one host and enforce spend caps.

Every tick the keeper reconciles the registry with live pids, restarts
genuine crashes (never budget/owner/auth halts) within a bounded budget,
sums every organizer-paid ledger against the cluster cap, rotates logs,
checks disk, and writes ``status.json`` for the wall display. It never
touches ``lab/`` state files except ``daemon.log`` rotation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from efferents import daemon
from efferents import steer as steer_mod
from efferents.agents.notify import notify_all
from efferents.agents.state import runs_count
from efferents.cluster.budget import cluster_spend
from efferents.cluster.config import (
    ClusterConfig,
    clear_control_flag,
    control_flag,
    daemon_env,
    set_control_flag,
    write_event,
)
from efferents.cluster.edges import derive_edges, edge_summary
from efferents.registry import LabRecord, Registry

# Halt-reason prefixes that are decisions, not crashes. Never auto-restart.
_DECISION_HALTS = ("budget:", "owner:", "auth:", "no credit:")


@dataclass
class LabStatus:
    lab_id: str
    status: str  # running | paused | halted | crashed | stopped
    pid: int | None
    submission_dir: str
    runs: int
    spend_usd: float
    cap_usd: float | None
    last_activity: str | None
    halt_reason: str | None
    restarts: int
    papers: int
    owner_name: str | None
    domain: str | None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _halt_reason(lab_root: Path) -> str | None:
    halt = lab_root / "halt_reason.txt"
    if halt.is_file():
        text = halt.read_text().strip()
        if text:
            return text
    state = _read_json(lab_root / "state.json")
    if state.get("status") == "paused" and state.get("halt_reason"):
        return str(state["halt_reason"])
    return None


def _ledger_total(path: Path) -> float:
    total = 0.0
    if not path.is_file():
        return total
    for line in path.read_text().splitlines():
        try:
            total += float(json.loads(line).get("cost_usd", 0.0) or 0.0)
        except (ValueError, TypeError):
            continue
    return total


def _rss_gb(pids: list[int]) -> float:
    total_kb = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total_kb += int(line.split()[1])
                    break
        except (OSError, ValueError, IndexError):
            continue
    return round(total_kb / 1024 / 1024, 3)


def host_info(cluster_root: Path, pids: list[int]) -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        info["load1"] = round(os.getloadavg()[0], 2)
    except OSError:
        info["load1"] = None
    try:
        usage = shutil.disk_usage(cluster_root)
        info["disk_free_gb"] = round(usage.free / 1e9, 2)
    except OSError:
        info["disk_free_gb"] = None
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            mem[key] = int(rest.split()[0])
        info["mem_total_gb"] = round(mem["MemTotal"] / 1024 / 1024, 2)
        info["mem_used_gb"] = round((mem["MemTotal"] - mem["MemAvailable"]) / 1024 / 1024, 2)
    except (OSError, KeyError, ValueError):
        info["mem_total_gb"] = info["mem_used_gb"] = None
    info["daemon_rss_gb"] = _rss_gb(pids)
    return info


class Keeper:
    def __init__(self, cfg: ClusterConfig, *, python: str = sys.executable,
                 run: Any = None, sleep: Any = None):
        self.cfg = cfg
        self.paths = cfg.paths
        self.sup = cfg.supervision
        self._python = python
        # Resolved at call time so tests can patch subprocess.run / time.sleep.
        self._run = run or (lambda *a, **kw: subprocess.run(*a, **kw))
        self._sleep = sleep or (lambda s: time.sleep(s))
        self._notified: dict[str, float] = {}
        self.tick_no = 0

    # --- inspection ------------------------------------------------------------

    def _restarts_in_window(self, lab_id: str) -> int:
        if not self.paths.restarts.is_file():
            return 0
        cutoff = _now() - timedelta(minutes=self.sup.restart_window_min)
        n = 0
        for line in self.paths.restarts.read_text().splitlines():
            try:
                rec = json.loads(line)
                if rec.get("lab_id") == lab_id and datetime.fromisoformat(rec["ts"]) >= cutoff:
                    n += 1
            except (ValueError, KeyError):
                continue
        return n

    def inspect(self, record: LabRecord) -> LabStatus:
        sub = Path(record.submission_dir)
        lab_root = Path(record.lab_root)
        pidfile_pid = daemon.read_pidfile(lab_root / "daemon.pid")
        pid = pidfile_pid or (record.pid or None)
        alive = pid is not None and daemon.is_pid_alive(pid)
        halt = _halt_reason(lab_root)
        if alive:
            status = "paused" if (halt and halt.startswith("owner:")) else "running"
        elif record.status == "running":
            status = "halted" if (halt and halt.startswith(_DECISION_HALTS)) else "crashed"
        else:
            status = "halted" if halt else "stopped"
        raw = _read_json(sub / "owner.json")
        cap = None
        try:
            import yaml  # noqa: PLC0415
            lab_yaml = yaml.safe_load((sub / "lab.yaml").read_text()) or {}
            cap_raw = (lab_yaml.get("budget") or {}).get("total_cap_usd")
            cap = float(cap_raw) if cap_raw is not None else None
            domain = lab_yaml.get("domain")
        except Exception:
            domain = None
        state_json = lab_root / "state.json"
        last_activity = (
            _iso(datetime.fromtimestamp(state_json.stat().st_mtime, tz=timezone.utc))
            if state_json.exists() else None
        )
        runs_db = lab_root / "runs.sqlite"
        try:
            n_runs = runs_count(runs_db) if runs_db.exists() else 0
        except Exception:
            n_runs = 0
        papers = 0
        for d in (sub / "paper", lab_root / "paper"):
            if d.is_dir():
                papers += len([p for p in d.glob("*.md") if p.name not in (
                    "journal.md", "external_journal.md", "incoming_reviews.md",
                    "reproductions.md", "rejected.md")])
        return LabStatus(
            lab_id=record.lab_id, status=status, pid=pid if alive else None,
            submission_dir=str(sub), runs=n_runs,
            spend_usd=round(_ledger_total(lab_root / "budget.jsonl"), 4), cap_usd=cap,
            last_activity=last_activity, halt_reason=halt,
            restarts=self._restarts_in_window(record.lab_id), papers=papers,
            owner_name=raw.get("owner_name"), domain=domain,
        )

    # --- actions ---------------------------------------------------------------

    def _start(self, record: LabRecord, *, reason: str) -> bool:
        cmd = [self._python, "-m", "efferents", "start", "--submission", record.submission_dir,
               "--lab-root", record.lab_root, "--detach"]
        result = self._run(cmd, cwd=record.submission_dir, env=daemon_env(self.cfg),
                           text=True, capture_output=True, timeout=60, check=False)
        ok = getattr(result, "returncode", 1) == 0
        with self.paths.restarts.open("a") as fh:
            fh.write(json.dumps({"ts": _iso(_now()), "lab_id": record.lab_id,
                                 "reason": reason, "ok": ok}) + "\n")
        write_event(self.paths, "restart" if ok else "restart_failed", lab_id=record.lab_id,
                    reason=reason, detail=(getattr(result, "stderr", "") or "")[-300:])
        return ok

    def _notify(self, key: str, title: str, message: str, *, min_interval_s: float = 300.0) -> None:
        now = time.monotonic()
        if now - self._notified.get(key, -1e9) < min_interval_s:
            return
        self._notified[key] = now
        try:
            notify_all(title=f"[{self.cfg.name}] {title}", message=message, priority=4)
        except Exception:
            pass

    def _rotate_logs(self, statuses: list[LabStatus]) -> None:
        limit = self.sup.log_rotate_mb * 1024 * 1024
        for st in statuses:
            log = Path(st.submission_dir) / "lab" / "daemon.log"
            try:
                if log.is_file() and log.stat().st_size > limit:
                    shutil.copyfile(log, log.with_suffix(".log.1"))
                    with log.open("r+") as fh:  # copy-truncate keeps the daemon's fd valid
                        fh.truncate(0)
            except OSError:
                continue

    def pause_all(self, *, by: str, reason: str) -> int:
        n = 0
        for record in Registry().list():
            try:
                steer_mod.steer(record.submission_dir, text=reason, by=by, action="pause",
                                lab_root=record.lab_root)
                n += 1
            except Exception:
                continue
        set_control_flag(self.paths, "pause_all", reason)
        write_event(self.paths, "pause_all", by=by, reason=reason, labs=n)
        return n

    def resume_all(self, *, by: str, reason: str) -> int:
        clear_control_flag(self.paths, "pause_all")
        clear_control_flag(self.paths, "frozen")
        n = 0
        for record in Registry().list():
            try:
                steer_mod.steer(record.submission_dir, text=reason, by=by, action="resume",
                                lab_root=record.lab_root)
                n += 1
            except Exception:
                continue
        write_event(self.paths, "resume_all", by=by, reason=reason, labs=n)
        return n

    # --- the tick ----------------------------------------------------------------

    def tick(self) -> dict:
        self.tick_no += 1
        registry = Registry()
        records = registry.list()
        statuses = [self.inspect(r) for r in records]

        # 1. Restart genuine crashes, bounded and staggered.
        starts = 0
        pause_all = control_flag(self.paths, "pause_all")
        stop_starts = control_flag(self.paths, "stop_starts")
        for record, st in zip(records, statuses):
            if st.status != "crashed" or pause_all or stop_starts:
                continue
            if control_flag(self.paths, f"halt_{record.lab_id}"):
                continue
            if st.restarts >= self.sup.max_restarts_per_lab:
                set_control_flag(self.paths, f"halt_{record.lab_id}",
                                 f"{st.restarts} restarts in {self.sup.restart_window_min} min")
                registry.update_status(record.lab_id, "crashed")
                self._notify(f"quarantine:{record.lab_id}", f"{record.lab_id} quarantined",
                             "crashed repeatedly; see lab/last_traceback.txt")
                continue
            if starts >= self.sup.max_starts_per_tick:
                break
            if starts:
                self._sleep(self.sup.start_stagger_s)
            self._start(record, reason=f"crash (halt_reason={st.halt_reason!r})")
            starts += 1

        # 2. Spend against the cluster cap.
        spend = cluster_spend(self.paths)
        cap = self.cfg.caps.cluster_total_usd
        spend["cap"] = cap
        if cap > 0 and spend["total"] >= cap and not control_flag(self.paths, "frozen"):
            set_control_flag(self.paths, "frozen", f"cluster cap ${cap:.2f} reached")
            self.pause_all(by="cluster-keeper", reason=f"event budget ${cap:.2f} reached")
            self._notify("cap", "Cluster cap reached",
                         f"${spend['total']:.2f} of ${cap:.2f}; every lab paused",
                         min_interval_s=0)
        elif cap > 0 and spend["total"] >= cap * self.cfg.caps.warn_at_fraction:
            self._notify("cap_warn", "Cluster spend warning",
                         f"${spend['total']:.2f} of ${cap:.2f}", min_interval_s=1800)

        # 3. Housekeeping.
        self._rotate_logs(statuses)
        pids = [st.pid for st in statuses if st.pid]
        host = host_info(self.paths.root, pids)
        free = host.get("disk_free_gb")
        if free is not None and free < self.sup.min_free_disk_gb:
            set_control_flag(self.paths, "stop_starts", f"disk free {free} GB")
            self._notify("disk", "Low disk", f"{free} GB free; new starts blocked")

        # 4. Status file for the wall display and the server.
        counts: dict[str, int] = {}
        for st in statuses:
            counts[st.status] = counts.get(st.status, 0) + 1
        edges = derive_edges([{"lab_id": st.lab_id} for st in statuses], self.paths.root)
        status = {
            "ts": _iso(_now()),
            "keeper_pid": os.getpid(),
            "tick": self.tick_no,
            "cluster": self.cfg.name,
            "frozen": control_flag(self.paths, "frozen"),
            "pause_all": pause_all,
            "totals": {
                "labs": len(statuses),
                **counts,
                "spend_usd": spend["total"],
                "cap_usd": cap,
                "reviews_spend_usd": spend["reviews"],
                "intake_spend_usd": spend["intake"],
                "runs": sum(st.runs for st in statuses),
                "papers": sum(st.papers for st in statuses),
                "edges": edge_summary(edges),
            },
            "host": host,
            "labs": [st.as_dict() for st in statuses],
        }
        tmp = self.paths.status.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(status, indent=2))
        os.replace(tmp, self.paths.status)
        return status

    def run(self, *, once: bool = False) -> None:
        while True:
            try:
                status = self.tick()
                totals = status["totals"]
                print(f"[keeper] tick {status['tick']}: {totals['labs']} labs "
                      f"({totals.get('running', 0)} running, {totals.get('crashed', 0)} crashed) "
                      f"spend ${totals['spend_usd']:.2f}/${totals['cap_usd']:.2f}", flush=True)
            except Exception as e:  # keep the keeper alive through a bad tick
                print(f"[keeper] tick failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            if once:
                return
            self._sleep(self.sup.tick_s)

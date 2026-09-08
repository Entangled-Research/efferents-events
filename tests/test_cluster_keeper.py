from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from efferents import daemon
from efferents.cluster import keeper as kp
from efferents.cluster.config import control_flag, set_control_flag
from efferents.registry import LabRecord, Registry
from tests.cluster_helpers import make_cluster


def _lab(cfg, lab_id: str, *, status="running", pid=4242, cap=12.0, spend=0.0,
         halt: str | None = None, owner="Ada", domain="synthetic") -> LabRecord:
    sub = cfg.paths.labs / lab_id
    lab_root = sub / "lab"
    lab_root.mkdir(parents=True)
    (sub / "lab.yaml").write_text(yaml.safe_dump({
        "lab_id": lab_id, "domain": domain,
        "budget": {"total_cap_usd": cap, "daily_cap_usd": cap},
    }))
    (sub / "owner.json").write_text(json.dumps({"owner_id": "o1", "owner_name": owner}))
    (lab_root / "state.json").write_text("{}")
    if spend:
        (lab_root / "budget.jsonl").write_text(json.dumps({"cost_usd": spend}) + "\n")
    if halt:
        (lab_root / "halt_reason.txt").write_text(halt + "\n")
    if pid:
        (lab_root / "daemon.pid").write_text(str(pid))
    rec = LabRecord(lab_id=lab_id, submission_dir=str(sub), lab_root=str(lab_root),
                    pid=pid or 0, started_at="2026-09-20T13:00:00+00:00", status=status)
    Registry().register(rec)
    return rec


@pytest.fixture
def keeper(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, supervision={"max_restarts_per_lab": 2,
                                                            "start_stagger_s": 0})
    alive: set[int] = set()
    monkeypatch.setattr(daemon, "is_pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(kp, "notify_all", lambda **kw: None)
    runs: list[list[str]] = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    k = kp.Keeper(cfg, python="python", run=fake_run, sleep=lambda s: None)
    return cfg, k, alive, runs


def test_tick_classifies_and_restarts_only_crashes(keeper):
    cfg, k, alive, runs = keeper
    _lab(cfg, "alive-lab", pid=1)
    alive.add(1)
    _lab(cfg, "paused-lab", pid=2, halt="owner: coffee")
    alive.add(2)
    _lab(cfg, "crashed-lab", pid=3)
    _lab(cfg, "budget-lab", pid=4, halt="budget: total cap reached")
    _lab(cfg, "stopped-lab", status="stopped", pid=0)
    status = k.tick()
    by_id = {line["lab_id"]: line["status"] for line in status["labs"]}
    assert by_id == {"alive-lab": "running", "paused-lab": "paused", "crashed-lab": "crashed",
                     "budget-lab": "halted", "stopped-lab": "stopped"}
    assert len(runs) == 1 and "crashed-lab" in " ".join(runs[0])
    assert status["totals"]["labs"] == 5 and status["totals"]["running"] == 1
    assert cfg.paths.status.exists() and cfg.paths.restarts.exists()
    assert status["labs"][0]["owner_name"] == "Ada"


def test_restart_budget_then_quarantine(keeper):
    cfg, k, alive, runs = keeper
    _lab(cfg, "flaky", pid=9)
    k.tick()
    k.tick()
    assert len(runs) == 2
    k.tick()
    assert len(runs) == 2  # third crash within the window → quarantine
    assert control_flag(cfg.paths, "halt_flaky")
    assert Registry().get("flaky").status == "crashed"
    k.tick()
    assert len(runs) == 2


def test_pause_all_and_stop_starts_block_restarts(keeper):
    cfg, k, alive, runs = keeper
    _lab(cfg, "crashed", pid=5)
    set_control_flag(cfg.paths, "stop_starts", "test")
    k.tick()
    assert runs == []


def test_cluster_cap_freezes_and_pauses_everything(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, caps={"cluster_total_usd": 10.0})
    monkeypatch.setattr(daemon, "is_pid_alive", lambda pid: True)
    notes = []
    monkeypatch.setattr(kp, "notify_all", lambda **kw: notes.append(kw))
    k = kp.Keeper(cfg, run=lambda *a, **kw: SimpleNamespace(returncode=0), sleep=lambda s: None)
    _lab(cfg, "spender-a", pid=1, spend=6.0)
    _lab(cfg, "spender-b", pid=2, spend=5.0)
    status = k.tick()
    assert status["frozen"] is True and control_flag(cfg.paths, "pause_all")
    assert status["totals"]["spend_usd"] == 11.0
    for lab_id in ("spender-a", "spender-b"):
        recs = [json.loads(line) for line in
                (cfg.paths.labs / lab_id / "lab" / "steering.jsonl").read_text().splitlines()]
        assert recs[-1]["action"] == "pause" and recs[-1]["by"] == "cluster-keeper"
    assert any("cap" in n["title"].lower() for n in notes)
    # resume-all lifts both flags
    assert k.resume_all(by="operator", reason="raised cap") == 2
    assert not control_flag(cfg.paths, "frozen") and not control_flag(cfg.paths, "pause_all")


def test_log_rotation_copy_truncate(keeper):
    cfg, k, alive, runs = keeper
    rec = _lab(cfg, "chatty", pid=1)
    alive.add(1)
    log = Path(rec.lab_root) / "daemon.log"
    log.write_text("x" * (int(cfg.supervision.log_rotate_mb * 1024 * 1024) + 10))
    k.tick()
    assert log.stat().st_size == 0
    assert (Path(rec.lab_root) / "daemon.log.1").stat().st_size > 0


def test_status_edges_summary_from_review_files(keeper):
    cfg, k, alive, runs = keeper
    _lab(cfg, "a", pid=1)
    _lab(cfg, "b", pid=2)
    alive.update({1, 2})
    reviews = cfg.paths.shared_journal / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "b__a__c1.md").write_text("---\nreviewer_lab: b\nreviewed_lab: a\ncampaign_id: c1\nstatus: open\n---\n")
    status = k.tick()
    assert status["totals"]["edges"] == {"reviewed": 1}

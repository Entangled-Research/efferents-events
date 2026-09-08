from __future__ import annotations

import json
from types import SimpleNamespace

import yaml

import efferents.cli as cli
from efferents import daemon
from efferents.cluster import keeper as kp
from efferents.registry import LabRecord, Registry
from tests.cluster_helpers import make_cluster


def _lab(cfg, lab_id, *, pid=0, status="stopped"):
    sub = cfg.paths.labs / lab_id
    (sub / "lab").mkdir(parents=True)
    (sub / "lab.yaml").write_text(yaml.safe_dump({"lab_id": lab_id, "domain": "d",
                                                  "budget": {"total_cap_usd": 12.0}}))
    (sub / "lab" / "state.json").write_text("{}")
    Registry().register(LabRecord(lab_id=lab_id, submission_dir=str(sub), lab_root=str(sub / "lab"),
                                  pid=pid, started_at="", status=status))
    return sub


def test_status_pause_all_and_resume_all(tmp_path, monkeypatch, capsys):
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setattr(kp, "notify_all", lambda **kw: None)
    monkeypatch.setattr(daemon, "is_pid_alive", lambda pid: False)
    a = _lab(cfg, "lab-a")
    _lab(cfg, "lab-b")
    assert cli.main(["cluster", "status", str(cfg.paths.root), "--refresh"]) == 0
    out = capsys.readouterr().out
    assert "labs=2" in out and "lab-a" in out and "lab-b" in out
    assert cli.main(["cluster", "status", str(cfg.paths.root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["labs"] == 2

    assert cli.main(["cluster", "pause-all", str(cfg.paths.root), "--reason", "break"]) == 0
    recs = [json.loads(line) for line in (a / "lab" / "steering.jsonl").read_text().splitlines()]
    assert recs[-1]["action"] == "pause" and recs[-1]["by"] == "operator" and recs[-1]["text"] == "break"
    assert (cfg.paths.controls / "pause_all").exists()
    assert cli.main(["cluster", "resume-all", str(cfg.paths.root)]) == 0
    assert not (cfg.paths.controls / "pause_all").exists()
    recs = [json.loads(line) for line in (a / "lab" / "steering.jsonl").read_text().splitlines()]
    assert recs[-1]["action"] == "resume"

    assert cli.main(["cluster", "pause", str(cfg.paths.root), "--lab-id", "lab-b",
                     "--by", "masha"]) == 0
    recs = [json.loads(line) for line in
            (cfg.paths.labs / "lab-b" / "lab" / "steering.jsonl").read_text().splitlines()]
    assert recs[-1]["action"] == "pause" and recs[-1]["by"] == "masha"
    assert cli.main(["cluster", "pause", str(cfg.paths.root), "--lab-id", "nope"]) == 1


def test_raise_cap_edits_yaml_and_restarts(tmp_path, monkeypatch, capsys):
    cfg = make_cluster(tmp_path, monkeypatch)
    monkeypatch.setattr(kp, "notify_all", lambda **kw: None)
    monkeypatch.setattr(daemon, "is_pid_alive", lambda pid: False)
    sub = _lab(cfg, "lab-a")
    calls = []
    monkeypatch.setattr(kp.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0, stderr=""))
    assert cli.main(["cluster", "raise-cap", str(cfg.paths.root), "--lab-id", "lab-a",
                     "--total", "18"]) == 0
    raw = yaml.safe_load((sub / "lab.yaml").read_text())
    assert raw["budget"]["total_cap_usd"] == 18.0 and raw["budget"]["daily_cap_usd"] == 18.0
    assert calls and "start" in calls[-1] and "--detach" in calls[-1]
    events = [json.loads(line)["event"] for line in cfg.paths.events.read_text().splitlines()]
    assert "raise_cap" in events


def test_registry_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFERENTS_HOME", str(tmp_path))
    Registry().register(LabRecord("x", "s", "line", 0, "", "stopped"))
    assert Registry().remove("x") is True
    assert Registry().get("x") is None and Registry().remove("x") is False

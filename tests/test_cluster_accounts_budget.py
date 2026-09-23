"""Allocation and recovery invariants across multiple labs and browser sessions."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from efferents.agents.budget import BudgetExhausted, CallUsage
from efferents.cluster.budget import coordinator, owner_intake_budget, owner_spend
from efferents.cluster.context import ClusterContext
from efferents.cluster.owners import OwnerStore
from tests.cluster_helpers import make_cluster


def ledger(path: Path, cost: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cost_usd": cost}) + "\n")


def test_owner_allocation_includes_intake_and_all_labs_without_double_charging_remote(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 50})
    ctx = ClusterContext(cfg, tracks={})
    ada, bob = ctx.owners.join("Ada"), ctx.owners.join("Bob")
    ledger(cfg.paths.root / "proxy" / ada.owner_id / "budget.jsonl", 15)
    ledger(cfg.paths.intake / ada.owner_id / "budget.jsonl", 0.5)
    ledger(cfg.paths.root / "proxy" / bob.owner_id / "budget.jsonl", 9)
    for lab_id in ("lab-a", "lab-b"):
        folder = ctx.hub.lab_dir(lab_id)
        folder.mkdir()
        (folder / "registration.json").write_text(json.dumps({"lab_id": lab_id, "owner_id": ada.owner_id}))
        (folder / "heartbeat.json").write_text(json.dumps({"spend_usd": 10}))
    budget = owner_spend(cfg, ada.owner_id)
    assert budget["spent_usd"] == 15.5 and budget["remaining_usd"] == 34.5
    assert budget["lab_count"] == 2
    assert owner_spend(cfg, bob.owner_id)["spent_usd"] == 9


def test_concurrent_intake_and_proxy_share_one_remaining_allocation(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 1},
                       intake={"cap_per_owner_usd": 1}, caps={"cluster_total_usd": 10})
    owner = OwnerStore(cfg.paths.owners).join("Ada")
    shared = coordinator(cfg)
    def reserve(family):
        try:
            return shared.reserve(owner.owner_id, .6, family=family)
        except BudgetExhausted:
            return None
    with ThreadPoolExecutor(2) as pool:
        reservations = list(pool.map(reserve, ("proxy", "intake")))
    assert sum(item is not None for item in reservations) == 1
    for item in reservations:
        if item:
            shared.release(item)
    assert reserve("proxy") is not None


def test_intake_reservation_released_after_success_and_failure(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    budget = owner_intake_budget(cfg, "owner")
    budget.reserve("openai/gpt-5.6-luna", 200, 100)
    assert coordinator(cfg).pending
    budget.record(agent="intake", model="openai/gpt-5.6-luna", usage=CallUsage(100, 100))
    assert not coordinator(cfg).pending
    budget.reserve("openai/gpt-5.6-luna", 200, 100)
    budget.release()
    assert not coordinator(cfg).pending


def test_merge_preserves_tokens_sessions_ledgers_and_lab_ownership(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 50})
    ctx = ClusterContext(cfg, tracks={})
    target, source, other = (ctx.owners.join(name) for name in ("Masha", "Test", "Other"))
    old_token = source.token
    old_key = ctx.owners.create_recovery_key(source.owner_id)
    sid = ctx.intake.create_session(source)["session"]["session_id"]
    remote = ctx.hub.lab_dir("quantum-lab")
    remote.mkdir()
    (remote / "registration.json").write_text(json.dumps({"lab_id": "quantum-lab", "owner_id": source.owner_id}))
    (remote / "heartbeat.json").write_text(json.dumps({"runs": 31, "spend_usd": 8}))
    ledger(cfg.paths.root / "proxy" / source.owner_id / "budget.jsonl", 8)
    ledger(cfg.paths.root / "proxy" / target.owner_id / "budget.jsonl", 12)
    ledger(cfg.paths.intake / source.owner_id / "budget.jsonl", .25)
    result = ctx.merge_accounts(target.owner_id, [source.owner_id], reason="User requested consolidation of verified test accounts")
    assert result["owner_budget"]["spent_usd"] == 20.25
    assert ctx.owners.by_token(old_token).owner_id == target.owner_id
    assert ctx.owners.recover(old_key).owner_id == target.owner_id
    assert len(ctx.owners.all()) == 2
    assert ctx.owners.by_token(other.token).owner_id == other.owner_id
    assert ctx.intake.get(target, sid)["session"]["session_id"] == sid
    assert len(ctx.intake.list_sessions(target)) == 1
    assert ctx.hub.require_owner(target, "quantum-lab")["owner_id"] == target.owner_id
    assert json.loads((remote / "heartbeat.json").read_text())["runs"] == 31
    assert ctx.cluster_payload(target)["my_labs"] == ["quantum-lab"]
    reloaded = OwnerStore(cfg.paths.owners)
    assert reloaded.by_token(old_token).owner_id == target.owner_id
    assert (cfg.paths.root / "proxy" / source.owner_id / "budget.jsonl").is_file()
    with pytest.raises(BudgetExhausted):
        coordinator(cfg).reserve(source.owner_id, 31, family="proxy")
    # Idempotent replay does not duplicate labs or spend.
    repeated = ctx.merge_accounts(target.owner_id, [source.owner_id], reason="Reconcile")
    assert repeated["owner_budget"]["spent_usd"] == 20.25
    assert repeated["owner"]["labs"] == ["quantum-lab"]


def test_remote_commands_deliver_once_and_ack_without_losing_evidence(tmp_path, monkeypatch):
    from efferents.cluster.remote_control import apply_commands, command_acks, pending_commands, queue_command
    from efferents.steer import read_steering
    from efferents.dashboard.control import ControlError
    cfg = make_cluster(tmp_path, monkeypatch)
    ctx = ClusterContext(cfg, tracks={})
    ada, bob = ctx.owners.join("Ada"), ctx.owners.join("Bob")
    remote = ctx.hub.lab_dir("chemistry")
    remote.mkdir()
    (remote / "registration.json").write_text(json.dumps({"lab_id": "chemistry", "owner_id": ada.owner_id}))
    with pytest.raises(ControlError):
        queue_command(ctx.hub, bob, "chemistry", "steer", {"message": "hijack"})
    first = queue_command(ctx.hub, ada, "chemistry", "steer", {"message": "Use scaffold split; report coverage."})
    queue_command(ctx.hub, ada, "chemistry", "pause", {"reason": "Review evidence"})
    submission = tmp_path / "chemistry"
    (submission / "lab").mkdir(parents=True)
    (submission / "lab" / "evidence.json").write_text('{"runs":42}')
    pending = pending_commands(ctx.hub, ada, "chemistry", {})
    apply_commands(submission, submission / "lab", pending)
    apply_commands(submission, submission / "lab", pending)
    records = read_steering(submission / "lab")
    assert len(records) == 2 and records[0]["remote_command_id"] == first["command_id"]
    assert records[1]["action"] == "pause"
    assert "Use scaffold split" in (submission / "context" / "popper.md").read_text()
    assert (submission / "lab" / "evidence.json").read_text() == '{"runs":42}'
    assert pending_commands(ctx.hub, ada, "chemistry", {"command_acks": command_acks(submission / "lab")}) == []
    assert all(item["delivered_at"] for item in json.loads((remote / "commands.json").read_text()))


def test_diagnostics_scrubs_provider_and_owner_tokens_and_reports_eval_sync(tmp_path, monkeypatch):
    from efferents.cluster.diagnostics import diagnostics
    cfg = make_cluster(tmp_path, monkeypatch)
    ctx = ClusterContext(cfg, tracks={})
    owner = ctx.owners.join("Ada")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-provider-value")
    folder = ctx.hub.lab_dir("chem-lab")
    folder.mkdir()
    (folder / "registration.json").write_text(json.dumps({"lab_id": "chem-lab", "owner_id": owner.owner_id}))
    (folder / "heartbeat.json").write_text(json.dumps({
        "halt_reason": f"Failed Bearer {owner.token} and sk-private-provider-value",
        "eval_sync_error": "InvalidSnapshot",
    }))
    (folder / "owner-evals.json").write_text(json.dumps({"synced_at": "2026-09-23T22:00:00+00:00"}))
    report = diagnostics(ctx, owner)
    assert owner.token not in json.dumps(report)
    assert "sk-private-provider-value" not in json.dumps(report)
    assert report["labs"][0]["eval_sync_error"] == "InvalidSnapshot"
    assert report["labs"][0]["eval_synced_at"] == "2026-09-23T22:00:00+00:00"
    assert report["labs"][0]["eval_snapshot_present"] is True


def test_pending_reservations_survive_process_restart_and_share_exact_cap(tmp_path, monkeypatch):
    from efferents.cluster.budget import SpendCoordinator, owner_budget
    cfg = make_cluster(tmp_path, monkeypatch, proxy={"cap_per_owner_usd": 1, "cap_total_usd": 2},
                       caps={"cluster_total_usd": 10})
    owner = OwnerStore(cfg.paths.owners).join("Ada")
    original = SpendCoordinator(cfg)
    key = original.reserve(owner.owner_id, .600009, family="proxy")
    restarted = SpendCoordinator(cfg)
    assert restarted.reservations(owner.owner_id)[0]["id"] == key
    with pytest.raises(BudgetExhausted):
        restarted.reserve(owner.owner_id, .4, family="proxy")
    report = owner_budget(cfg, owner.owner_id)
    assert report["spent_usd"] == 0 and report["reserved_usd"] == .6
    restarted.release(key)
    assert original.reservations(owner.owner_id) == []
    assert restarted.reserve(owner.owner_id, 1, family="proxy")


def test_intake_rejected_call_releases_but_transport_uncertainty_holds(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    budget = owner_intake_budget(cfg, "owner")
    budget.reserve("openai/gpt-5.6-luna", 200, 100)
    rejected = RuntimeError("provider rejected")
    rejected.status_code = 429
    budget.finish_error(rejected)
    assert coordinator(cfg).reservations("owner") == []
    budget.reserve("openai/gpt-5.6-luna", 200, 100)
    budget.finish_error(TimeoutError("response lost"))
    budget.release()  # request cleanup must not erase the uncertain hold
    assert len(coordinator(cfg).reservations("owner")) == 1

import json

import pytest

from efferents.agents.budget import BudgetTracker, CallUsage, cost_usd
from efferents.cluster import billing
from efferents.cluster.budget import cluster_spend, owner_budget
from tests.cluster_helpers import make_cluster


def case(tmp_path, monkeypatch):
    cfg = make_cluster(tmp_path, monkeypatch)
    owner = cfg.paths.root / "proxy/o1/budget.jsonl"
    event = cfg.paths.root / "proxy/budget.jsonl"
    owner.parent.mkdir(parents=True)
    original = BudgetTracker(owner).record(agent="proxy", model="openai/gpt-5.6-sol",
                                           usage=CallUsage(1000, 100), notes="owner=o1 reservation=r1")
    BudgetTracker(event).record(agent="proxy", model=original["model"], usage=CallUsage(1000, 100),
                                notes=original["notes"])
    usage = {**original, "agent": "reviewer", "input_tokens": 100, "cache_read_input_tokens": 900,
             "cost_usd": cost_usd(original["model"], CallUsage(100, 100, cache_read_input_tokens=900))}
    evidence = {"source": "/retained/lab/budget.jsonl", "file_sha256": "a" * 64,
                "record_sha256": billing.record_sha256(usage), "line": 1}
    kwargs = {"owner_id": "o1", "original_sha256": billing.record_sha256(original),
              "usage_record": usage, "evidence": evidence}
    return cfg, owner, event, usage, kwargs


def test_verified_credit_preserves_rows_and_updates_both_budgets_once(tmp_path, monkeypatch):
    cfg, owner, event, usage, kwargs = case(tmp_path, monkeypatch)
    originals = {path: path.read_bytes() for path in (owner, event)}
    preview = billing.credit_cached_input(cfg, **kwargs)
    assert preview["status"] == "preview" and preview["credit_usd"] > 0
    assert all(path.read_bytes() == original for path, original in originals.items())
    applied = billing.credit_cached_input(cfg, **kwargs, apply=True)
    assert applied["ledger_writes"] == 2
    assert all(path.read_bytes().startswith(original) for path, original in originals.items())
    assert owner_budget(cfg, "o1")["spent_usd"] == round(usage["cost_usd"], 4)
    assert cluster_spend(cfg.paths, precision=None)["proxy"] == pytest.approx(usage["cost_usd"])
    assert owner_budget(cfg, "other")["spent_usd"] == 0
    assert billing.credit_cached_input(cfg, **kwargs, apply=True)["status"] == "already_applied"
    assert all(len(path.read_text().splitlines()) == 2 for path in (owner, event))


def test_retry_repairs_only_missing_second_ledger(tmp_path, monkeypatch):
    cfg, owner, event, usage, kwargs = case(tmp_path, monkeypatch)
    append = billing._append
    def fail_event(path, record):
        if path == event:
            raise OSError("disk failure after first fsynced ledger")
        append(path, record)
    monkeypatch.setattr(billing, "_append", fail_event)
    with pytest.raises(OSError):
        billing.credit_cached_input(cfg, **kwargs, apply=True)
    monkeypatch.setattr(billing, "_append", append)
    assert billing.credit_cached_input(cfg, **kwargs, apply=True)["ledger_writes"] == 1
    assert len(owner.read_text().splitlines()) == len(event.read_text().splitlines()) == 2
    assert json.loads(owner.read_text().splitlines()[-1]) == json.loads(event.read_text().splitlines()[-1])


@pytest.mark.parametrize("damage", ["partial", "duplicate", "wrong_usage", "conflicting_credit", "ambiguous_calls"])
def test_invalid_or_ambiguous_evidence_never_credits(tmp_path, monkeypatch, damage):
    cfg, owner, event, usage, kwargs = case(tmp_path, monkeypatch)
    if damage == "partial":
        with owner.open("a") as handle:
            handle.write('{"partial":')
    elif damage == "duplicate":
        with event.open("a") as handle:
            handle.write(event.read_text())
    elif damage == "wrong_usage":
        kwargs["usage_record"] = {**usage, "output_tokens": 101}
        kwargs["evidence"]["record_sha256"] = billing.record_sha256(kwargs["usage_record"])
    elif damage == "ambiguous_calls":
        for path in (owner, event):
            row = {**json.loads(path.read_text().splitlines()[0]), "notes": "owner=o1 reservation=another"}
            with path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
    else:
        identifier = billing.credit_cached_input(cfg, **kwargs)["adjustment_id"]
        with owner.open("a") as handle:
            handle.write(json.dumps({"adjustment_id": identifier, "cost_usd": -100}) + "\n")
    before = {path: path.read_bytes() for path in (owner, event)}
    with pytest.raises(ValueError):
        billing.credit_cached_input(cfg, **kwargs, apply=True)
    assert all(path.read_bytes() == data for path, data in before.items())

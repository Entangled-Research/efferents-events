"""Organizer-paid ledgers: per-owner intake caps, the cluster intake cap,
and the cluster-wide spend total the keeper enforces."""

from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path
from typing import Any

from efferents.agents.budget import BudgetExhausted, BudgetTracker, CallUsage, read_jsonl
from efferents.cluster.config import ClusterConfig, ClusterPaths


class DualBudget:
    """A budget facade charging two ``BudgetTracker`` ledgers per call.

    ``RoutingMessagesClient`` only needs ``reserve``; the intake code calls
    ``record`` after each response. ``BudgetTracker`` is not thread-safe, so
    both ledgers are guarded by one lock.
    """

    def __init__(self, primary: BudgetTracker, secondary: BudgetTracker, *,
                 cfg: ClusterConfig | None = None, owner_id: str | None = None):
        self.primary = primary
        self.secondary = secondary
        self._lock = threading.Lock()
        self.cfg, self.owner_id = cfg, owner_id
        self._reservation: str | None = None

    def reserve(self, model: str, max_tokens: int | None, input_estimate: int = 0) -> float:
        with self._lock:
            estimate = self.primary.reserve(model, max_tokens, input_estimate)
            self.secondary.reserve(model, max_tokens, input_estimate)
            if self.cfg is not None:
                self.release()
                self._reservation = coordinator(self.cfg).reserve(
                    self.owner_id, estimate, family="intake")
            return estimate

    def record(self, *, agent: str, model: str, usage: CallUsage, notes: str | None = None) -> dict:
        with self._lock:
            rec = self.primary.record(agent=agent, model=model, usage=usage, notes=notes)
            self.secondary.record(agent=agent, model=model, usage=usage, notes=notes)
            self.release()
            return rec

    def release(self) -> None:
        if self._reservation is not None:
            coordinator(self.cfg).release(self._reservation)
            self._reservation = None

    def spend_primary(self) -> float:
        with self._lock:
            return self.primary.spend_total()


def owner_intake_budget(cfg: ClusterConfig, owner_id: str) -> DualBudget:
    paths = cfg.paths
    owner_dir = paths.intake / owner_id
    owner_dir.mkdir(parents=True, exist_ok=True)
    cap = cfg.intake.cap_per_owner_usd
    total = cfg.intake.cap_total_usd
    # Daily cap == lifetime cap: an event lives inside one day, and the
    # lifetime check yields the clearer "used up" message.
    return DualBudget(
        BudgetTracker(owner_dir / "budget.jsonl", daily_cap_usd=cap, total_cap_usd=cap),
        BudgetTracker(paths.intake_ledger, daily_cap_usd=total, total_cap_usd=total),
        cfg=cfg, owner_id=owner_id,
    )


def usage_from_response(response: Any) -> CallUsage:
    usage = getattr(response, "usage", None)
    return CallUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    )


def _ledger_sum(path: Path) -> float:
    if not path.exists():
        return 0.0
    return float(sum(r.get("cost_usd", 0.0) or 0.0 for r in read_jsonl(path)))


def cluster_spend(paths: ClusterPaths, *, precision: int | None = 4) -> dict[str, float]:
    """Every organizer-paid dollar so far, by ledger family."""
    labs = 0.0
    if paths.labs.is_dir():
        for lab_dir in paths.labs.iterdir():
            labs += _ledger_sum(lab_dir / "lab" / "budget.jsonl")
    intake = _ledger_sum(paths.intake_ledger)
    reviews = _ledger_sum(paths.reviews_ledger)
    proxy = _ledger_sum(paths.root / "proxy" / "budget.jsonl")
    display = (lambda value: round(value, precision)) if precision is not None else (lambda value: value)
    return {
        "labs": display(labs),
        "intake": display(intake),
        "reviews": display(reviews),
        "proxy": display(proxy),
        "total": display(labs + intake + reviews + proxy),
    }


def _owner_ids(cfg: ClusterConfig, owner_id: str) -> list[str]:
    from efferents.cluster.owners import OwnerStore
    owner = OwnerStore(cfg.paths.owners).by_id(owner_id)
    return owner.identity_ids if owner else [owner_id]


def owner_spend(cfg: ClusterConfig, owner_id: str, *, precision: int | None = 4) -> dict:
    """One participant allocation, including original ledgers of merged identities.

    Remote heartbeat spend is a mirror of proxy charges, never another charge.
    Hosted ledgers are included because those calls use the provider directly.
    """
    ids = _owner_ids(cfg, owner_id)
    proxy = sum(_ledger_sum(cfg.paths.root / "proxy" / oid / "budget.jsonl") for oid in ids)
    intake = sum(_ledger_sum(cfg.paths.intake / oid / "budget.jsonl") for oid in ids)
    labs = 0.0
    lab_ids = set()
    for parent, metadata in ((cfg.paths.labs, "owner.json"),
                             (cfg.paths.root / "network" / "labs", "registration.json")):
        for path in parent.glob(f"*/{metadata}"):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if record.get("owner_id") not in ids:
                continue
            lab_ids.add(record.get("lab_id") or path.parent.name)
            if metadata == "owner.json":
                labs += _ledger_sum(path.parent / "lab" / "budget.jsonl")
    total = proxy + intake + labs
    cap = float(cfg.proxy.cap_per_owner_usd)
    display = (lambda value: round(value, precision)) if precision is not None else (lambda value: value)
    return {"spent_usd": display(total), "cap_usd": cap,
            "remaining_usd": display(max(0.0, cap - total)),
            "lab_count": len(lab_ids),
            "breakdown": {"proxy": display(proxy), "intake": display(intake),
                          "labs": display(labs)}}


class SpendCoordinator:
    """Serialize reservations across every intake session and proxy lab request."""

    def __init__(self, cfg: ClusterConfig):
        self.cfg = cfg
        self.lock = threading.RLock()
        self.pending: dict[str, tuple[str, str, float]] = {}

    def reserve(self, owner_id: str, estimate: float, *, family: str) -> str:
        with self.lock:
            ids = _owner_ids(self.cfg, owner_id)
            total = owner_spend(self.cfg, owner_id, precision=None)["spent_usd"]
            pending = sum(value for oid, _, value in self.pending.values() if oid in ids)
            cap = float(self.cfg.proxy.cap_per_owner_usd)
            if total + pending + estimate > cap:
                raise BudgetExhausted("participant total", spend=total + pending,
                                      cap=cap, estimate=estimate)
            cluster = cluster_spend(self.cfg.paths, precision=None)["total"]
            cluster_pending = sum(value for _, _, value in self.pending.values())
            if cluster + cluster_pending + estimate > self.cfg.caps.cluster_total_usd:
                raise BudgetExhausted("event total", spend=cluster + cluster_pending,
                                      cap=self.cfg.caps.cluster_total_usd, estimate=estimate)
            if family == "intake":
                owner_intake = owner_spend(self.cfg, owner_id, precision=None)["breakdown"]["intake"]
                family_pending = sum(value for oid, f, value in self.pending.values()
                                     if oid in ids and f == family)
                if owner_intake + family_pending + estimate > self.cfg.intake.cap_per_owner_usd:
                    raise BudgetExhausted("intake", spend=owner_intake + family_pending,
                                          cap=self.cfg.intake.cap_per_owner_usd, estimate=estimate)
                intake_pending = sum(value for _, f, value in self.pending.values() if f == family)
                if cluster_spend(self.cfg.paths, precision=None)["intake"] + intake_pending + estimate > self.cfg.intake.cap_total_usd:
                    raise BudgetExhausted("event intake", spend=cluster_spend(self.cfg.paths, precision=None)["intake"] + intake_pending,
                                          cap=self.cfg.intake.cap_total_usd, estimate=estimate)
            key = secrets.token_hex(16)
            self.pending[key] = (ids[0], family, estimate)
            return key

    def release(self, key: str) -> None:
        with self.lock:
            self.pending.pop(key, None)


_COORDINATORS: dict[str, SpendCoordinator] = {}
_COORDINATORS_LOCK = threading.Lock()


def coordinator(cfg: ClusterConfig) -> SpendCoordinator:
    key = str(cfg.paths.root.resolve())
    with _COORDINATORS_LOCK:
        value = _COORDINATORS.setdefault(key, SpendCoordinator(cfg))
        value.cfg = cfg
        return value

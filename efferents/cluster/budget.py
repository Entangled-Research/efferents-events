"""Organizer-paid ledgers: per-owner intake caps, the cluster intake cap,
and the cluster-wide spend total the keeper enforces."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from efferents.agents.budget import BudgetTracker, CallUsage, read_jsonl
from efferents.cluster.config import ClusterConfig, ClusterPaths


class DualBudget:
    """A budget facade charging two ``BudgetTracker`` ledgers per call.

    ``RoutingMessagesClient`` only needs ``reserve``; the intake code calls
    ``record`` after each response. ``BudgetTracker`` is not thread-safe, so
    both ledgers are guarded by one lock.
    """

    def __init__(self, primary: BudgetTracker, secondary: BudgetTracker):
        self.primary = primary
        self.secondary = secondary
        self._lock = threading.Lock()

    def reserve(self, model: str, max_tokens: int | None, input_estimate: int = 0) -> float:
        with self._lock:
            estimate = self.primary.reserve(model, max_tokens, input_estimate)
            self.secondary.reserve(model, max_tokens, input_estimate)
            return estimate

    def record(self, *, agent: str, model: str, usage: CallUsage, notes: str | None = None) -> dict:
        with self._lock:
            rec = self.primary.record(agent=agent, model=model, usage=usage, notes=notes)
            self.secondary.record(agent=agent, model=model, usage=usage, notes=notes)
            return rec

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


def cluster_spend(paths: ClusterPaths) -> dict[str, float]:
    """Every organizer-paid dollar so far, by ledger family."""
    labs = 0.0
    if paths.labs.is_dir():
        for lab_dir in paths.labs.iterdir():
            labs += _ledger_sum(lab_dir / "lab" / "budget.jsonl")
    intake = _ledger_sum(paths.intake_ledger)
    reviews = _ledger_sum(paths.reviews_ledger)
    return {
        "labs": round(labs, 4),
        "intake": round(intake, 4),
        "reviews": round(reviews, 4),
        "total": round(labs + intake + reviews, 4),
    }

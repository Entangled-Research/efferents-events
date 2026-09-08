"""Shared helpers for cluster tests."""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE_TRACK = Path(__file__).parent / "fixtures" / "cluster_track"
SMOKE_HYP = Path(__file__).resolve().parents[1] / "examples" / "smoke-lab" / "hypothesis.md"


def make_popper_repo(monkeypatch, tmp_path: Path) -> Path:
    repo = tmp_path / "popper-probe"
    (repo / "skills" / "intake").mkdir(parents=True)
    (repo / "scripts").mkdir()
    real_skill = Path.home() / "Documents/popper-probe/skills/intake/SKILL.md"
    real_validator = Path.home() / "Documents/popper-probe/scripts/validate_hypothesis.py"
    (repo / "skills/intake/SKILL.md").write_text(
        real_skill.read_text() if real_skill.exists() else "# Stub SKILL.md\n"
    )
    if not real_validator.exists():
        pytest.skip("Real popper-probe validate_hypothesis.py not available")
    (repo / "scripts/validate_hypothesis.py").write_text(real_validator.read_text())
    monkeypatch.setenv("POPPER_PROBE_REPO", str(repo))
    return repo


def make_cluster(tmp_path: Path, monkeypatch, **overrides):
    from efferents.cluster import config as cc
    import yaml

    root = tmp_path / "cluster"
    cc.init_cluster(root)
    shutil.copytree(FIXTURE_TRACK, root / "tracks" / "coefficient-sweep")
    raw = yaml.safe_load((root / "cluster.yaml").read_text())
    raw["join_code"] = "popper-2026"
    raw["session"]["secure_cookies"] = False
    for key, value in overrides.items():
        if isinstance(value, dict):
            raw[key] = {**raw.get(key, {}), **value}
        else:
            raw[key] = value
    (root / "cluster.yaml").write_text(yaml.safe_dump(raw))
    cfg = cc.load_cluster_config(root)
    monkeypatch.setenv("EFFERENTS_HOME", str(cfg.paths.home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return cfg


class ScriptedClient:
    """Fake messages client returning scripted replies in order."""

    def __init__(self, replies, budget=None):
        # Shared by reference so a test can queue replies between turns.
        self.replies = replies
        self.calls: list[dict] = []
        self.budget = budget
        self.messages = self

    def create(self, **kwargs):
        if self.budget is not None:
            self.budget.reserve(kwargs.get("model", "m"), kwargs.get("max_tokens"), 100)
        self.calls.append(kwargs)
        text = self.replies.pop(0) if self.replies else "…"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
        )


VALID_HYP = """\
---
slug: coefficient-above-0-7-loss-below-0-1
created: 2026-09-20
status: active
falsifiability_gate: passed
literature_pass: none
---

## Original framing

A bigger coefficient always lowers the loss.

## Operational restatement

Runs with `coefficient` >= 0.7 report `synthetic_loss` < 0.1 on at least 4 of 5 seeds.

## Falsifier(s)

If the median `synthetic_loss` over >= 4 runs with `coefficient` >= 0.7 is >= 0.1,
the hypothesis is false.

## Test design

Sweep `coefficient` over {0.7, 0.8, 0.9} with 5 seeds each; record `synthetic_loss` per run.

## Auxiliary assumptions

The stub executor's hidden optimum does not change between runs.

## Distinctiveness

Distinct from "loss is monotone in coefficient": predicts a threshold, not a slope.

## References

## Intake log

- Probe 1: restated as a per-run metric threshold.
- Probe 2: falsifier named over the run ledger.
"""


def hypothesis_block(text: str | None = None) -> str:
    body = text if text is not None else VALID_HYP
    return "Here is the draft.\n\n```hypothesis.md\n" + body.rstrip("\n") + "\n```\n\nApprove, or tell me what to change?"

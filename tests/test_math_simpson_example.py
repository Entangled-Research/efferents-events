from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from efferents.journals import journal_for_domain
from efferents.lab import LabConfig
from efferents.onboarding import trial


EXAMPLE = Path(__file__).parents[1] / "examples" / "math-simpson-lab"


def test_math_simpson_example_runs_three_paired_function_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("EFFERENTS_HOME", str(tmp_path / "registry"))
    submission = tmp_path / "simpson-lab"
    shutil.copytree(EXAMPLE, submission)

    cfg = LabConfig.from_submission(submission)
    assert cfg.domain == "numerical-analysis"
    assert journal_for_domain(cfg.domain) == "Journal of Numerical Analysis"
    assert cfg.metrics.headline.comparator_column == "baseline_error"
    assert cfg.metrics.headline.aggregate == "max"

    result = trial(submission, runs=3)
    assert result["ok"] and result["runs"] == 3
    with sqlite3.connect(submission / "lab" / "runs.sqlite") as conn:
        rows = conn.execute(
            "SELECT seed, status, candidate_error, baseline_error, improvement_pct "
            "FROM runs ORDER BY seed"
        ).fetchall()

    assert [row[0] for row in rows] == [0, 1, 2]
    assert all(row[1] == "succeeded" for row in rows)
    assert all(row[2] <= 0.0001 for row in rows)
    assert max(row[3] for row in rows) == pytest.approx(0.000625)
    assert all(row[4] > 99.9 for row in rows)
    assert len(list((submission / "lab" / "artifacts").glob("quadrature-*.svg"))) == 3

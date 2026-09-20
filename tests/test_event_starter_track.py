"""The event starter is a usable cluster track, not a standalone lab fork."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from efferents.cluster.tracks import validate_track


TRACK = Path(__file__).resolve().parents[1] / "tracks" / "evacuation"


def test_evacuation_track_validates_without_preset_hypothesis_or_falsifiers():
    track = validate_track(TRACK)
    assert track.id == "evacuation"
    assert track.domain == "multi-agent-routing"
    assert track.comparison["axis"] == "policy"
    assert "evacuation_improvement_pct" in {column["name"] for column in track.columns}
    assert len(track.example_falsifiers) == 2
    assert not (track.submission / "hypothesis.md").exists()
    assert not track.lab_yaml.get("falsifiers")


def test_evacuation_track_runs_paired_seed_without_network(tmp_path):
    submission = tmp_path / "submission"
    shutil.copytree(TRACK / "submission", submission)
    result = subprocess.run(
        [sys.executable, "src/run_experiment.py", "--config", "configs/default.yaml"],
        cwd=submission, capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert {obs["dimensions"]["policy"] for obs in payload["observations"]} == {
        "static", "congestion",
    }
    assert 0 <= payload["metrics"]["candidate_completion_rate"] <= 1
    assert len(payload["artifacts"]) == 2
    for artifact in payload["artifacts"]:
        assert Path(artifact["path"]).is_file()

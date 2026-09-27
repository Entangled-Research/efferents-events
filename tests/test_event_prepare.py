"""A new event must not inherit credentials, participant state or open spending."""
from pathlib import Path
import runpy
import stat

import pytest

from efferents.cluster.config import load_cluster_config, control_flag

prepare = runpy.run_path(str(Path(__file__).parents[1] / "deploy/events/prepare.py"))["prepare"]


def test_fresh_event_is_private_empty_and_frozen(tmp_path):
    destination = tmp_path / "next"
    prepare(destination, "Next event", "https://event.example.org")
    cfg = load_cluster_config(destination / "cluster")
    assert cfg.name == "Next event"
    assert cfg.join_code != "change-me"
    assert not cfg.labs.hosted
    assert all(control_flag(cfg.paths, key) for key in ("frozen", "pause_all", "stop_starts"))
    assert not cfg.paths.owners.exists()
    assert not list(cfg.paths.labs.iterdir())
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / "hub.env").stat().st_mode) == 0o600
    assert "OPENAI_API_KEY=\n" in (destination / "hub.env").read_text()


def test_cannot_reset_existing_event(tmp_path):
    destination = tmp_path / "event"
    prepare(destination, "Original", "https://event.example.org")
    before = (destination / "cluster/cluster.yaml").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(destination, "Replacement", "https://event.example.org")
    assert (destination / "cluster/cluster.yaml").read_bytes() == before


def test_events_get_distinct_secrets(tmp_path):
    for name in ("one", "two"):
        prepare(tmp_path / name, name, "https://event.example.org")
    assert load_cluster_config(tmp_path / "one/cluster").join_code != load_cluster_config(tmp_path / "two/cluster").join_code
    assert (tmp_path / "one/hub.env").read_text() != (tmp_path / "two/hub.env").read_text()

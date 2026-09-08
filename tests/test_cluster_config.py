from __future__ import annotations

import os

import pytest
import yaml

from efferents.cluster import config as cc


def test_init_creates_skeleton_and_is_idempotent(tmp_path):
    root = tmp_path / "cluster"
    written = cc.init_cluster(root)
    assert {p.name for p in written} == {"cluster.yaml", ".env"}
    for name in ("home", "labs", "intake", "shared_journal", "controls", "tracks"):
        assert (root / name).is_dir(), name
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    assert cc.init_cluster(root) == []


def test_load_defaults_and_cadence(tmp_path):
    root = tmp_path / "c"
    cc.init_cluster(root)
    cfg = cc.load_cluster_config(root)
    assert cfg.name == "Research lab night" and cfg.join_code == "change-me"
    assert cfg.labs.total_cap_usd == 3.0 and cfg.labs.max_per_owner == 2
    assert cfg.caps.cluster_total_usd == 20.0
    assert cfg.cadence.runs_per_digest == 3 and cfg.cadence_raw["runs_per_paper"] == 5
    assert cfg.tracks_path == root / "tracks"
    assert cfg.supervision.tick_s == 30.0 and cfg.session.secure_cookies is True


@pytest.mark.parametrize("patch, needle", [
    ({"join_code": "ab"}, "join_code"),
    ({"labs": {"total_cap_usd": -1}}, "non-negative"),
    ({"labs": {"bogus": 1}}, "unknown keys"),
    ({"intake": {"max_turns": 2.5}}, "wrong type"),
    ({"caps": {"warn_at_fraction": 2}}, "warn_at_fraction"),
    ({"cadence": {"runs_per_digest": 0}}, "cadence.runs_per_digest"),
    ({"name": ""}, "name is required"),
])
def test_invalid_config_rejected(tmp_path, patch, needle):
    root = tmp_path / "c"
    cc.init_cluster(root)
    raw = yaml.safe_load((root / "cluster.yaml").read_text())
    for key, value in patch.items():
        if isinstance(value, dict):
            raw[key] = {**raw.get(key, {}), **value}
        else:
            raw[key] = value
    (root / "cluster.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(cc.ClusterConfigError, match=needle):
        cc.load_cluster_config(root)


def test_missing_config(tmp_path):
    with pytest.raises(cc.ClusterConfigError, match="cluster init"):
        cc.load_cluster_config(tmp_path)


def test_daemon_env_strips_notification_topic(tmp_path, monkeypatch):
    root = tmp_path / "c"
    cc.init_cluster(root)
    cfg = cc.load_cluster_config(root)
    monkeypatch.setenv("NTFY_TOPIC", "secret-topic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    env = cc.daemon_env(cfg, {"X": "1"})
    assert "NTFY_TOPIC" not in env
    assert env["ANTHROPIC_API_KEY"] == "k" and env["X"] == "1"
    assert env["EFFERENTS_HOME"] == str(root / "home")
    assert env["EFFERENTS_CLUSTER_DIR"] == str(root)


def test_activate_environment_points_registry_at_cluster(tmp_path, monkeypatch):
    root = tmp_path / "c"
    cc.init_cluster(root)
    (root / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n")
    monkeypatch.delenv("EFFERENTS_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = cc.load_cluster_config(root)
    cc.activate_environment(cfg)
    assert os.environ["EFFERENTS_HOME"] == str(root / "home")
    assert os.environ["ANTHROPIC_API_KEY"] == "from-dotenv"
    assert os.environ["EFFERENTS_MODEL"] == cfg.model


def test_control_flags_and_events(tmp_path):
    root = tmp_path / "c"
    cc.init_cluster(root)
    paths = cc.ClusterPaths(root)
    assert not cc.is_frozen(paths)
    cc.set_control_flag(paths, "frozen", "cap reached")
    assert cc.is_frozen(paths)
    cc.clear_control_flag(paths, "frozen")
    assert not cc.is_frozen(paths)
    rec = cc.write_event(paths, "join", owner_id="o1")
    assert rec["event"] == "join"
    assert '"owner_id": "o1"' in paths.events.read_text()

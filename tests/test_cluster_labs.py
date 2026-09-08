from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from efferents.cluster import config as cc
from efferents.cluster import labs as cl
from efferents.cluster.owners import OwnerStore
from efferents.cluster.tracks import load_tracks
from efferents.dashboard.control import ControlError
from efferents.lab import LabConfig
from efferents.registry import Registry

FIXTURE = Path(__file__).parent / "fixtures" / "cluster_track"
SMOKE_HYP = (Path(__file__).resolve().parents[1] / "examples" / "smoke-lab" / "hypothesis.md")


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    root = tmp_path / "cluster"
    cc.init_cluster(root)
    shutil.copytree(FIXTURE, root / "tracks" / "coefficient-sweep")
    cfg = cc.load_cluster_config(root)
    monkeypatch.setenv("EFFERENTS_HOME", str(cfg.paths.home))
    tracks = load_tracks(cfg.tracks_path)
    owners = OwnerStore(cfg.paths.owners)
    return cfg, tracks["coefficient-sweep"], owners


def test_create_lab_materialises_valid_submission(cluster):
    cfg, track, owners = cluster
    ada = owners.join("Ada")
    hyp = SMOKE_HYP.read_text()
    lab = cl.create_lab(
        cfg, track=track, owner=ada, hypothesis_text=hyp,
        first_claim="I think bigger coefficients always lose.", lab_id=None,
        falsifiers=[{"id": "F1", "description": "Median loss never drops below 0.1",
                     "when": {"column": "synthetic_loss", "agg": "median", "op": ">=",
                              "value": 0.1, "min_n": 4}}],
        design_notes="- mapped via test", session_id="s_abc",
    )
    dest = cfg.paths.labs / lab.cfg.lab_id
    assert dest.is_dir() and lab.owner_id == ada.owner_id and lab.track == "coefficient-sweep"
    reloaded = LabConfig.from_submission(dest)
    assert reloaded.lab_id == lab.cfg.lab_id
    assert reloaded.budget.total_cap_usd == 3.0 and reloaded.budget.daily_cap_usd == 3.0
    assert reloaded.cadence.runs_per_digest == 3
    assert reloaded.falsifiers[0].id == "F1"
    assert reloaded.autonomy.coder_enabled is False
    charter = (dest / "context" / "popper.md").read_text()
    assert "participant:Ada" in charter and "bigger coefficients always lose" in charter
    assert "mapped via test" in charter
    assert (dest / "popper-corpus").is_dir()
    assert (dest / "lab" / "runs.sqlite").exists() and (dest / "lab" / "state.json").exists()
    meta = json.loads((dest / "owner.json").read_text())
    assert meta["owner_name"] == "Ada" and meta["intake_session"] == "s_abc"
    rec = Registry().get(lab.cfg.lab_id)
    assert rec is not None and rec.status == "stopped"
    events = [json.loads(line) for line in cfg.paths.events.read_text().splitlines()]
    assert events[-1]["event"] == "lab_created"
    assert not (dest / "hypothesis.md.bak").exists()


def test_lab_id_rules_collisions_and_owner_limit(cluster):
    cfg, track, owners = cluster
    ada = owners.join("Ada")
    hyp = SMOKE_HYP.read_text()
    kw = dict(track=track, owner=ada, hypothesis_text=hyp, first_claim="c", falsifiers=None)
    with pytest.raises(ControlError, match="Lab ids"):
        cl.create_lab(cfg, lab_id="bad id!", **kw)
    first = cl.create_lab(cfg, lab_id="my-lab", **kw)
    owners.add_lab(ada.owner_id, first.cfg.lab_id)
    with pytest.raises(ControlError, match="taken"):
        cl.create_lab(cfg, lab_id="my-lab", **kw)
    # Derived id gets a suffix when the slug is taken.
    second = cl.create_lab(cfg, lab_id=None, **kw)
    owners.add_lab(ada.owner_id, second.cfg.lab_id)
    assert second.cfg.lab_id != first.cfg.lab_id
    with pytest.raises(ControlError, match="limit"):
        cl.create_lab(cfg, lab_id="third", **kw)


def test_rollback_on_failure(cluster, monkeypatch):
    cfg, track, owners = cluster
    ada = owners.join("Ada")
    monkeypatch.setattr(cl, "write_charter", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cl.create_lab(cfg, track=track, owner=ada, hypothesis_text=SMOKE_HYP.read_text(),
                      first_claim="c", lab_id="doomed", falsifiers=None)
    assert not (cfg.paths.labs / "doomed").exists()
    assert Registry().get("doomed") is None


def test_derive_lab_id():
    assert cl.derive_lab_id("Pea Plants & Music!", set()) == "pea-plants-music"
    assert cl.derive_lab_id("x", {"x"}) == "x-2"
    assert cl.slugify("") == "lab"

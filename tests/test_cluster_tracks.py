from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from efferents.cluster import tracks as tr

FIXTURE = Path(__file__).parent / "fixtures" / "cluster_track"


def _tracks_dir(tmp_path: Path, name: str = "coefficient-sweep") -> Path:
    root = tmp_path / "tracks"
    shutil.copytree(FIXTURE, root / name)
    return root


def test_valid_track_loads(tmp_path):
    tracks = tr.load_tracks(_tracks_dir(tmp_path))
    assert list(tracks) == ["coefficient-sweep"]
    t = tracks["coefficient-sweep"]
    assert t.domain == "synthetic" and t.columns[0]["name"] == "synthetic_loss"
    assert t.bucket_axes == ()
    assert "synthetic_loss" in t.catalogue_text() and "coefficient" in t.catalogue_text()
    assert "orientation only" in tr.catalogue_text(tracks)
    payload = t.payload()
    assert payload["id"] == "coefficient-sweep" and payload["knobs"][0]["name"] == "coefficient"


def _mutate(root: Path, fn):
    meta_path = root / "coefficient-sweep" / "track.yaml"
    meta = yaml.safe_load(meta_path.read_text())
    fn(meta, root / "coefficient-sweep")
    meta_path.write_text(yaml.safe_dump(meta))


@pytest.mark.parametrize("mutation, needle", [
    (lambda m, d: m["columns"].append({"name": "bad name"}), "columns"),
    (lambda m, d: m.update(bucket_axes=["depth"]), "bucket_axes"),
    (lambda m, d: m.update(columns=[{"name": "other"}]), "headline column"),
    (lambda m, d: m.pop("title"), "title and summary"),
    (lambda m, d: (d / "submission" / "hypothesis.md").write_text("x"), "must not ship"),
    (lambda m, d: (d / "submission" / "lab.yaml").unlink(), "lab.yaml is missing"),
])
def test_invalid_tracks_fail_fast(tmp_path, mutation, needle):
    root = _tracks_dir(tmp_path)
    _mutate(root, mutation)
    with pytest.raises(tr.TrackError, match=needle):
        tr.load_tracks(root)


def test_predefined_falsifiers_rejected(tmp_path):
    root = _tracks_dir(tmp_path)
    lab_yaml = root / "coefficient-sweep" / "submission" / "lab.yaml"
    raw = yaml.safe_load(lab_yaml.read_text())
    raw["falsifiers"] = [{"id": "F1", "description": "x",
                          "when": {"column": "synthetic_loss", "agg": "median", "op": ">=", "value": 1}}]
    lab_yaml.write_text(yaml.safe_dump(raw))
    with pytest.raises(tr.TrackError, match="predefine falsifiers"):
        tr.load_tracks(root)


def test_missing_dir_and_duplicate_ids(tmp_path):
    with pytest.raises(tr.TrackError, match="does not exist"):
        tr.load_tracks(tmp_path / "nope")
    root = _tracks_dir(tmp_path)
    shutil.copytree(root / "coefficient-sweep", root / "second")
    with pytest.raises(tr.TrackError, match="duplicate track id"):
        tr.load_tracks(root)

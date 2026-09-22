from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from efferents.cluster import binding as bd
from efferents.cluster.tracks import load_tracks

FIXTURE = Path(__file__).parent / "fixtures" / "cluster_track"
HYP = "---\nslug: loss-below\n---\n## Falsifier(s)\nmedian loss stays above 0.1\n"


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.replies.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _track(tmp_path):
    root = tmp_path / "tracks"
    shutil.copytree(FIXTURE, root / "coefficient-sweep")
    return load_tracks(root)["coefficient-sweep"]


GOOD = json.dumps({
    "falsifiers": [{"id": "F1", "description": "Median loss never drops below 0.1",
                    "when": {"column": "synthetic_loss", "agg": "median", "op": ">=",
                             "value": 0.1, "min_n": 4}}],
    "rationale": "The claim predicts the loss falls under 0.1.",
    "lab_id": "loss-below",
})


def test_valid_mapping_first_try(tmp_path):
    client = FakeClient([GOOD])
    b = bd.propose_falsifiers(HYP, _track(tmp_path), client=client, model="m")
    assert b.validated and b.attempts == 1
    assert b.falsifiers[0]["id"] == "F1"
    assert b.rules_text == ["median(synthetic_loss) >= 0.1"]
    assert b.lab_id_suggestion == "loss-below" and b.note == ""
    assert "Track description" in client.calls[0]["system"]


def test_retry_with_error_then_success(tmp_path):
    bad = json.dumps({"falsifiers": [{"id": "F1", "description": "x",
                                      "when": {"column": "nope", "agg": "median", "op": ">=", "value": 1}}],
                      "rationale": "", "lab_id": "x"})
    client = FakeClient([bad, GOOD])
    b = bd.propose_falsifiers(HYP, _track(tmp_path), client=client, model="m")
    assert b.validated and b.attempts == 2
    retry_prompt = client.calls[1]["messages"][-1]["content"]
    assert "failed validation" in retry_prompt and "nope" in retry_prompt


def test_two_failures_fall_back_to_undecided(tmp_path):
    client = FakeClient(["not json at all", "{\"falsifiers\": [{\"id\": \"bad id!\"}]}"])
    b = bd.propose_falsifiers(HYP, _track(tmp_path), client=client, model="m")
    assert not b.validated and b.falsifiers == [] and b.attempts == 2
    assert b.note == bd.UNDECIDED_NOTE and b.errors


def test_empty_rules_is_valid_but_noted(tmp_path):
    client = FakeClient([json.dumps({"falsifiers": [], "rationale": "cannot", "lab_id": "z"})])
    b = bd.propose_falsifiers(HYP, _track(tmp_path), client=client, model="m")
    assert b.validated and b.falsifiers == [] and b.note == bd.UNDECIDED_NOTE


def test_track_router_rejects_unrelated_executor(tmp_path):
    client = FakeClient([json.dumps({
        "action": "new", "track_id": None, "confidence": 0.99,
        "reason": "A coefficient sweep cannot evaluate an image-classification claim.",
    })])
    result = bd.select_track(
        "A quantum classifier outperforms a CNN on MNIST.",
        {"coefficient-sweep": _track(tmp_path)}, client=client, model="m",
    )
    assert result["action"] == "new" and result["track_id"] is None
    assert "Topic resemblance is insufficient" in client.calls[0]["system"]


def test_track_router_accepts_only_high_confidence_known_track(tmp_path):
    client = FakeClient([json.dumps({
        "action": "existing", "track_id": "coefficient-sweep", "confidence": 0.92,
        "reason": "The executor varies the coefficient and reports synthetic loss.",
    })])
    result = bd.select_track(
        HYP, {"coefficient-sweep": _track(tmp_path)}, client=client, model="m",
    )
    assert result["action"] == "existing"
    assert result["track_id"] == "coefficient-sweep"


def test_track_router_fails_closed_on_unknown_or_low_confidence_track(tmp_path):
    client = FakeClient([json.dumps({
        "action": "existing", "track_id": "coefficient-sweep", "confidence": 0.6,
        "reason": "Maybe.",
    })])
    result = bd.select_track(HYP, {"coefficient-sweep": _track(tmp_path)}, client=client, model="m")
    assert result["action"] == "new" and result["track_id"] is None

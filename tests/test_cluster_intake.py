from __future__ import annotations

import json

import pytest

from efferents.cluster.intake import IntakeStore, OPENING_LINE
from efferents.cluster.owners import OwnerStore
from efferents.cluster.tracks import load_tracks
from efferents.dashboard.control import ControlError
from tests.cluster_helpers import (
    ScriptedClient, hypothesis_block, make_cluster, make_popper_repo,
)


@pytest.fixture
def intake(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch)
    tracks = load_tracks(cfg.tracks_path)
    owners = OwnerStore(cfg.paths.owners)
    ada = owners.join("Ada")
    scripts: dict = {"replies": []}
    clients: list[ScriptedClient] = []

    def factory(budget):
        client = ScriptedClient(scripts["replies"], budget=budget)
        clients.append(client)
        return client

    store = IntakeStore(cfg, tracks, client_factory=factory, today=lambda: "2026-09-20")
    return store, ada, scripts, clients, cfg


def test_session_lifecycle_to_drafted(intake):
    store, ada, scripts, clients, cfg = intake
    payload = store.create_session(ada)
    sid = payload["session"]["session_id"]
    assert payload["session"]["state"] == "open"
    assert payload["transcript"][0]["text"] == OPENING_LINE
    assert store.list_sessions(ada)[0]["session_id"] == sid

    scripts["replies"].extend(["Can you restate that as a measurable quantity?"])
    payload = store.run_turn(ada, sid, "I think a bigger coefficient always lowers the loss.")
    assert payload["session"]["user_turns"] == 1
    assert payload["session"]["first_claim"].startswith("I think a bigger")
    assert payload["session"]["spend_usd"] > 0
    system = clients[-1].calls[0]["system"]
    assert "INTERACTIVE WEB MODE" in system and "Today: 2026-09-20" in system
    assert "coefficient-sweep" in system  # track catalogue as orientation
    # Messages start with the user's turn, never the static opening line.
    assert clients[-1].calls[0]["messages"][0]["role"] == "user"

    scripts["replies"].extend([hypothesis_block()])
    payload = store.run_turn(ada, sid, "Loss below 0.1 when coefficient is above 0.7.")
    assert payload["session"]["state"] == "drafted"
    assert payload["draft"]["valid"] and payload["draft"]["gate"] == "passed"
    assert payload["draft"]["slug"]
    assert payload["transcript"][-1]["draft_detected"] is True
    ledger = cfg.paths.intake / ada.owner_id / "budget.jsonl"
    assert ledger.exists() and cfg.paths.intake_ledger.exists()
    events = [json.loads(line)["event"] for line in cfg.paths.events.read_text().splitlines()]
    assert "session_open" in events and "draft_valid" in events


def test_invalid_draft_gets_one_automatic_correction(intake):
    store, ada, scripts, clients, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    broken = hypothesis_block("---\nslug: x\n---\n# missing everything\n")
    scripts["replies"].extend([broken, hypothesis_block()])
    payload = store.run_turn(ada, sid, "claim")
    assert len(clients[-1].calls) == 2
    fix_request = clients[-1].calls[1]["messages"][-1]["content"]
    assert "validate_hypothesis.py reported" in fix_request
    assert payload["session"]["state"] == "drafted"
    assert payload["draft"]["validator_attempts"] == 2
    notes = [t for t in payload["transcript"] if t["role"] == "note"]
    assert notes and "Validator reported errors" in notes[0]["text"]


def test_persistently_invalid_draft_is_surfaced_not_stored(intake):
    store, ada, scripts, clients, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    broken = hypothesis_block("---\nslug: x\n---\n# nope\n")
    scripts["replies"].extend([broken, broken])
    payload = store.run_turn(ada, sid, "claim")
    assert payload["session"]["state"] == "open"
    assert payload["draft"]["valid"] is False and payload["draft"]["errors"]


def test_failed_gate_marks_unfalsifiable(intake):
    store, ada, scripts, clients, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    failed = (
        "---\nslug: vibes\ncreated: 2026-09-20\nstatus: unfalsifiable\n"
        "falsifiability_gate: failed\nliterature_pass: none\n---\n\n"
        "## Original framing\n\nEverything is connected.\n\n## Diagnostic\n\n"
        "No observation could contradict it.\n\n## References\n\n## Intake log\n\n- probed\n"
    )
    scripts["replies"].extend([hypothesis_block(failed)])
    payload = store.run_turn(ada, sid, "everything is connected")
    assert payload["session"]["state"] == "unfalsifiable"
    with pytest.raises(ControlError, match="passed the falsifiability gate"):
        store.approve(ada, sid)


def test_approve_bind_and_notes(intake):
    store, ada, scripts, clients, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    scripts["replies"].extend([hypothesis_block()])
    store.run_turn(ada, sid, "claim")
    with pytest.raises(ControlError, match="Approve the hypothesis"):
        store.bind(ada, sid, "coefficient-sweep")
    payload = store.approve(ada, sid)
    assert payload["session"]["state"] == "approved"
    with pytest.raises(ControlError, match="no longer accepting"):
        store.run_turn(ada, sid, "more")
    with pytest.raises(ControlError, match="Unknown track"):
        store.bind(ada, sid, "nope")
    scripts["replies"].extend([json.dumps({
        "falsifiers": [{"id": "F1", "description": "Median loss stays >= 0.1",
                        "when": {"column": "synthetic_loss", "agg": "median", "op": ">=",
                                 "value": 0.1, "min_n": 4}}],
        "rationale": "The claim needs the loss to fall.", "lab_id": "coef-lab",
    })])
    payload = store.bind(ada, sid, "coefficient-sweep")
    assert payload["session"]["state"] == "bound"
    assert payload["binding"]["validated"] and payload["binding"]["rules_text"]
    from efferents.cluster.intake import Draft, Session
    sess = payload["session"]
    notes = store.design_notes(Session(draft=Draft(**sess["draft"]),
                                       **{k: v for k, v in sess.items() if k != "draft"}))
    assert "Track: coefficient-sweep" in notes and "median(synthetic_loss) >= 0.1" in notes


def test_automatic_route_binds_compatible_executor(intake):
    store, ada, scripts, _, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    scripts["replies"].append(hypothesis_block())
    store.run_turn(ada, sid, "coefficient above 0.7 lowers loss below 0.1")
    store.approve(ada, sid)
    scripts["replies"].extend([
        json.dumps({
            "action": "existing", "track_id": "coefficient-sweep", "confidence": 0.96,
            "reason": "The executor varies coefficient and reports synthetic loss.",
        }),
        json.dumps({
            "falsifiers": [{"id": "F1", "description": "Median loss stays >= 0.1",
                            "when": {"column": "synthetic_loss", "agg": "median",
                                     "op": ">=", "value": 0.1, "min_n": 4}}],
            "rationale": "The track measures the claimed outcome.", "lab_id": "coef-lab",
        }),
    ])
    payload = store.route(ada, sid)
    assert payload["session"]["state"] == "bound"
    assert payload["session"]["routing"]["track_id"] == "coefficient-sweep"
    assert payload["binding"]["validated"] is True
    events = [json.loads(line)["event"] for line in cfg.paths.events.read_text().splitlines()]
    assert "intake_routed" in events


def test_automatic_route_creates_no_hosted_lab_for_unrelated_idea(intake):
    store, ada, scripts, *_ = intake
    sid = store.create_session(ada)["session"]["session_id"]
    scripts["replies"].append(hypothesis_block())
    store.run_turn(ada, sid, "a quantum classifier outperforms a CNN on MNIST")
    store.approve(ada, sid)
    scripts["replies"].append(json.dumps({
        "action": "new", "track_id": None, "confidence": 0.99,
        "reason": "The available executor cannot run quantum or MNIST experiments.",
    }))
    payload = store.route(ada, sid)
    assert payload["session"]["state"] == "approved"
    assert payload["session"]["routing"]["action"] == "new"
    assert payload["binding"] is None and payload["session"]["track_id"] is None


def test_limits_turns_sessions_and_budget(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch, intake={
        "max_turns": 1, "max_sessions_per_owner": 1, "cap_per_owner_usd": 0.0001,
    })
    tracks = load_tracks(cfg.tracks_path)
    ada = OwnerStore(cfg.paths.owners).join("Ada")
    store = IntakeStore(cfg, tracks, client_factory=lambda b: ScriptedClient(["hi"], budget=b))
    sid = store.create_session(ada)["session"]["session_id"]
    with pytest.raises(ControlError, match="open intake"):
        store.create_session(ada)
    with pytest.raises(ControlError) as exc:
        store.run_turn(ada, sid, "claim")
    assert exc.value.status == 402  # owner cap too small for even one call
    store.abandon(ada, sid)
    store.create_session(ada)  # allowed again once the first is abandoned


def test_frozen_cluster_blocks_dialogue(intake):
    store, ada, scripts, clients, cfg = intake
    sid = store.create_session(ada)["session"]["session_id"]
    from efferents.cluster.config import set_control_flag
    set_control_flag(cfg.paths, "frozen", "test")
    with pytest.raises(ControlError, match="frozen"):
        store.run_turn(ada, sid, "claim")
    with pytest.raises(ControlError, match="frozen"):
        store.create_session(ada)


def test_unknown_session_and_bad_input(intake):
    store, ada, *_ = intake
    with pytest.raises(ControlError) as exc:
        store.get(ada, "s_000000000000")
    assert exc.value.status == 404
    with pytest.raises(ControlError) as exc:
        store.get(ada, "../escape")
    assert exc.value.status == 404
    sid = store.create_session(ada)["session"]["session_id"]
    with pytest.raises(ControlError, match="Type something"):
        store.run_turn(ada, sid, "   ")


def test_provider_failure_rolls_back_the_turn(tmp_path, monkeypatch):
    make_popper_repo(monkeypatch, tmp_path)
    cfg = make_cluster(tmp_path, monkeypatch)
    tracks = load_tracks(cfg.tracks_path)
    ada = OwnerStore(cfg.paths.owners).join("Ada")

    class Boom:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("provider down")

    store = IntakeStore(cfg, tracks, client_factory=lambda b: Boom())
    sid = store.create_session(ada)["session"]["session_id"]
    with pytest.raises(ControlError) as exc:
        store.run_turn(ada, sid, "my claim")
    assert exc.value.status == 502
    payload = store.get(ada, sid)
    assert payload["session"]["user_turns"] == 0 and payload["session"]["first_claim"] == ""
    roles = [t["role"] for t in payload["transcript"]]
    assert roles == ["assistant", "note"]  # user line removed, failure note kept

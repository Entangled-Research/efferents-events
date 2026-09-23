"""Browser popper-probe dialogue: sessions, turns, drafts, approval, binding.

State per session lives under ``intake/<owner_id>/<session_id>/``:
``session.json`` (state machine + spend), ``transcript.jsonl`` (every turn),
``draft/hypothesis.md`` (last valid draft) and ``binding.json``.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from efferents.agents.budget import BudgetExhausted
from efferents.agents.popper_gate import (
    INTERACTIVE_INSTRUCTION,
    _extract_text,
    _skill_md,
    extract_hypothesis_block,
    frontmatter_value,
    validate_hypothesis_text,
)
from efferents.cluster.binding import Binding, propose_falsifiers, select_track
from efferents.cluster.budget import DualBudget, owner_intake_budget, usage_from_response
from efferents.cluster.config import ClusterConfig, is_frozen, write_event
from efferents.cluster.owners import Owner
from efferents.cluster.tracks import Track, catalogue_text
from efferents.dashboard.control import ControlError

STATES = ("open", "drafted", "unfalsifiable", "approved", "bound", "created", "abandoned")
OPENING_LINE = (
    "Describe the claim you want to test, in your own words. I will push back "
    "until it has a falsifier an experiment could actually trip."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Draft:
    text: str = ""
    slug: str | None = None
    valid: bool = False
    errors: str = ""
    gate: str | None = None  # passed | failed
    hash: str | None = None
    validator_attempts: int = 0


@dataclass
class Session:
    session_id: str
    owner_id: str
    owner_name: str
    created_at: str
    state: str = "open"
    model: str = ""
    user_turns: int = 0
    spend_usd: float = 0.0
    first_claim: str = ""
    draft: Draft = field(default_factory=Draft)
    track_id: str | None = None
    lab_id: str | None = None
    binding: dict | None = None
    routing: dict | None = None
    updated_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


class IntakeStore:
    def __init__(
        self,
        cfg: ClusterConfig,
        tracks: dict[str, Track],
        *,
        client_factory: Callable[[DualBudget], Any],
        today: Callable[[], str] = lambda: date.today().isoformat(),
    ):
        self.cfg = cfg
        self.tracks = tracks
        self._client_factory = client_factory
        self._today = today
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._catalogue = catalogue_text(tracks)

    # --- paths -----------------------------------------------------------------

    def _owner_dir(self, owner_id: str) -> Path:
        return self.cfg.paths.intake / owner_id

    def _session_dir(self, owner_id: str, session_id: str) -> Path:
        return self._owner_dir(owner_id) / session_id

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    # --- persistence -----------------------------------------------------------

    def _save(self, session: Session) -> None:
        session.updated_at = _now()
        d = self._session_dir(session.owner_id, session.session_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "session.json.tmp"
        tmp.write_text(json.dumps(session.to_dict(), indent=2))
        tmp.replace(d / "session.json")

    def _load(self, owner: Owner, session_id: str) -> Session:
        if not session_id or "/" in session_id or session_id.startswith("."):
            raise ControlError("Unknown intake session.", status=404)
        path = next((self._session_dir(oid, session_id) / "session.json"
                     for oid in owner.identity_ids
                     if (self._session_dir(oid, session_id) / "session.json").is_file()),
                    self._session_dir(owner.owner_id, session_id) / "session.json")
        if not path.is_file():
            raise ControlError("Unknown intake session.", status=404)
        data = json.loads(path.read_text())
        draft = Draft(**(data.pop("draft", None) or {}))
        return Session(draft=draft, **data)

    def _append_transcript(self, session: Session, **rec: Any) -> None:
        d = self._session_dir(session.owner_id, session.session_id)
        with (d / "transcript.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": _now(), **rec}) + "\n")

    def _drop_last_user_turn(self, session: Session) -> None:
        path = self._session_dir(session.owner_id, session.session_id) / "transcript.jsonl"
        if not path.is_file():
            return
        lines = path.read_text().splitlines()
        for i in range(len(lines) - 1, -1, -1):
            try:
                if json.loads(lines[i]).get("role") == "user":
                    del lines[i]
                    break
            except ValueError:
                continue
        path.write_text("".join(line + "\n" for line in lines))

    def transcript(self, session: Session) -> list[dict]:
        path = self._session_dir(session.owner_id, session.session_id) / "transcript.jsonl"
        if not path.is_file():
            return []
        out = []
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    # --- queries -----------------------------------------------------------------

    def list_sessions(self, owner: Owner) -> list[dict]:
        roots = [self._owner_dir(oid) for oid in owner.identity_ids]
        out = []
        for d in sorted(p for root in roots if root.is_dir()
                        for p in root.iterdir() if p.is_dir()):
            path = d / "session.json"
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text())
            except ValueError:
                continue
            out.append({
                "session_id": data.get("session_id"),
                "state": data.get("state"),
                "created_at": data.get("created_at"),
                "draft_slug": (data.get("draft") or {}).get("slug"),
                "lab_id": data.get("lab_id"),
                "track_id": data.get("track_id"),
            })
        return out

    def get(self, owner: Owner, session_id: str) -> dict:
        session = self._load(owner, session_id)
        return self.payload(session)

    def payload(self, session: Session) -> dict:
        return {
            "session": session.to_dict(),
            "transcript": self.transcript(session),
            "draft": asdict(session.draft),
            "binding": session.binding,
            "spend": {
                "session_usd": round(session.spend_usd, 4),
                "owner_cap_usd": self.cfg.intake.cap_per_owner_usd,
            },
            "tracks": [t.payload() for t in self.tracks.values()],
        }

    # --- session lifecycle -----------------------------------------------------

    def create_session(self, owner: Owner) -> dict:
        if is_frozen(self.cfg.paths):
            raise ControlError("The event budget is frozen; no new intakes.", status=409)
        active = [s for s in self.list_sessions(owner)
                  if s["state"] not in ("created", "abandoned")]
        if len(active) >= self.cfg.intake.max_sessions_per_owner:
            raise ControlError(
                f"You have {len(active)} open intake(s); finish or abandon one first.",
                status=409,
            )
        session = Session(
            session_id="s_" + secrets.token_hex(6),
            owner_id=owner.owner_id,
            owner_name=owner.name,
            created_at=_now(),
            model=self.cfg.model,
        )
        self._save(session)
        self._append_transcript(session, role="assistant", text=OPENING_LINE, cost_usd=0.0)
        write_event(self.cfg.paths, "session_open", owner_id=owner.owner_id,
                    session_id=session.session_id)
        return self.payload(session)

    def abandon(self, owner: Owner, session_id: str) -> dict:
        session = self._load(owner, session_id)
        if session.state == "created":
            raise ControlError("This intake already produced a lab.", status=409)
        session.state = "abandoned"
        self._save(session)
        return self.payload(session)

    # --- the dialogue ------------------------------------------------------------

    def _system_prompt(self) -> str:
        parts = [_skill_md(), INTERACTIVE_INSTRUCTION, f"Today: {self._today()}"]
        if self._catalogue:
            parts.append(self._catalogue)
        return "\n\n".join(parts)

    def _messages(self, session: Session) -> list[dict]:
        out = []
        for rec in self.transcript(session):
            role = rec.get("role")
            if role in ("user", "assistant") and rec.get("text"):
                out.append({"role": role, "content": rec["text"]})
        # The API requires the first message to be the user's; drop the
        # static opening line if it leads.
        while out and out[0]["role"] == "assistant":
            out.pop(0)
        return out

    def run_turn(self, owner: Owner, session_id: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ControlError("Type something for the probe to work with.")
        if len(text) > self.cfg.intake.message_max_chars:
            raise ControlError(
                f"Messages are at most {self.cfg.intake.message_max_chars} characters."
            )
        if "\x00" in text:
            raise ControlError("Message contains an invalid null byte.")
        if is_frozen(self.cfg.paths):
            raise ControlError("The event budget is frozen; the dialogue is paused.", status=409)
        lock = self._lock_for(session_id)
        if not lock.acquire(blocking=False):
            raise ControlError("The probe is still thinking; wait for its reply.", status=409)
        try:
            session = self._load(owner, session_id)
            if session.state in ("approved", "bound", "created", "abandoned"):
                raise ControlError("This intake is no longer accepting messages.", status=409)
            if session.user_turns >= self.cfg.intake.max_turns:
                raise ControlError(
                    "This intake reached its turn limit; approve the draft or start over.",
                    status=409,
                )
            first_claim_was_empty = not session.first_claim
            if first_claim_was_empty:
                session.first_claim = text
            session.user_turns += 1
            self._append_transcript(session, role="user", text=text)
            self._save(session)

            budget = owner_intake_budget(self.cfg, owner.owner_id)
            client = self._client_factory(budget)
            try:
                reply = self._model_turn(session, client, budget, self._messages(session))
            except ControlError:
                # The participant's message did not reach the probe: undo the
                # turn so a retry does not duplicate it (the note stays).
                self._drop_last_user_turn(session)
                session.user_turns -= 1
                if first_claim_was_empty:
                    session.first_claim = ""
                self._save(session)
                raise
            self._append_transcript(session, role="assistant", text=reply["text"],
                                    cost_usd=reply["cost"], draft_detected=reply["draft"] is not None)
            if reply["draft"] is not None:
                self._ingest_draft(session, client, budget, reply["draft"])
            self._save(session)
            return self.payload(session)
        finally:
            if "budget" in locals():
                budget.release()
            lock.release()

    def _model_turn(self, session: Session, client: Any, budget: DualBudget,
                    messages: list[dict]) -> dict:
        try:
            response = client.messages.create(
                model=self.cfg.model,
                max_tokens=self.cfg.intake.max_tokens,
                system=self._system_prompt(),
                messages=messages,
            )
        except BudgetExhausted as e:
            self._append_transcript(session, role="note",
                                    text="Your intake budget is used up.", cost_usd=0.0)
            self._save(session)
            raise ControlError(
                "Your intake budget for this event is used up. You can still approve "
                "a draft you already have.", status=402,
            ) from e
        except ControlError:
            raise
        except Exception as e:  # provider outage, bad key, network: tell the participant
            kind = getattr(e, "kind", type(e).__name__)
            self._append_transcript(session, role="note",
                                    text=f"The model provider failed ({kind}); try again.",
                                    cost_usd=0.0)
            self._save(session)
            raise ControlError(
                f"The model provider failed ({kind}). Try again in a moment; the "
                "organizer has been notified if it persists.", status=502,
            ) from e
        usage = usage_from_response(response)
        rec = budget.record(agent="popper_intake", model=self.cfg.model, usage=usage,
                            notes=f"session={session.session_id}")
        cost = float(rec.get("cost_usd", 0.0))
        session.spend_usd += cost
        text = _extract_text(response)
        return {"text": text, "cost": cost, "draft": extract_hypothesis_block(text)}

    def _ingest_draft(self, session: Session, client: Any, budget: DualBudget,
                      draft_text: str) -> None:
        scratch = self._session_dir(session.owner_id, session.session_id) / "draft"
        ok, errors = validate_hypothesis_text(draft_text, scratch)
        attempts = 1
        if not ok:
            # One automatic correction pass, as the headless gate does.
            self._append_transcript(
                session, role="note",
                text=f"Validator reported errors; asked the probe to correct them.\n{errors}",
                cost_usd=0.0,
            )
            fix_request = (
                "validate_hypothesis.py reported:\n\n" + errors +
                "\n\nRe-emit the complete corrected hypothesis.md in a `hypothesis.md` "
                "fenced block. Same rules apply."
            )
            messages = self._messages(session) + [
                {"role": "assistant", "content": "```hypothesis.md\n" + draft_text + "```"},
                {"role": "user", "content": fix_request},
            ]
            try:
                reply = self._model_turn(session, client, budget, messages)
            except ControlError:
                reply = None
            attempts = 2
            if reply is not None:
                self._append_transcript(session, role="assistant", text=reply["text"],
                                        cost_usd=reply["cost"],
                                        draft_detected=reply["draft"] is not None)
                if reply["draft"] is not None:
                    draft_text = reply["draft"]
                    ok, errors = validate_hypothesis_text(draft_text, scratch)
        session.draft.validator_attempts = attempts
        session.draft.errors = "" if ok else errors
        if not ok:
            session.draft.valid = False
            return
        gate = frontmatter_value(draft_text, "falsifiability_gate")
        session.draft = Draft(
            text=draft_text,
            slug=frontmatter_value(draft_text, "slug"),
            valid=True,
            errors="",
            gate=gate,
            hash="sha256:" + __import__("hashlib").sha256(draft_text.encode()).hexdigest(),
            validator_attempts=attempts,
        )
        session.state = "drafted" if gate == "passed" else "unfalsifiable"
        write_event(self.cfg.paths, "draft_valid", owner_id=session.owner_id,
                    session_id=session.session_id, gate=gate, slug=session.draft.slug)

    # --- approve / bind / create -------------------------------------------------

    def approve(self, owner: Owner, session_id: str) -> dict:
        session = self._load(owner, session_id)
        if session.draft.valid and session.draft.gate != "passed":
            raise ControlError("Only a draft that passed the falsifiability gate can be approved.",
                               status=409)
        if session.state not in ("drafted", "approved", "bound") or not session.draft.valid:
            raise ControlError("There is no gated draft to approve yet.", status=409)
        if session.state == "drafted":
            session.state = "approved"
            self._save(session)
            write_event(self.cfg.paths, "draft_approved", owner_id=owner.owner_id,
                        session_id=session_id, slug=session.draft.slug)
        return self.payload(session)

    def bind(self, owner: Owner, session_id: str, track_id: str) -> dict:
        session = self._load(owner, session_id)
        if session.state not in ("approved", "bound"):
            raise ControlError("Approve the hypothesis before choosing a track.", status=409)
        track = self.tracks.get(track_id or "")
        if track is None:
            raise ControlError("Unknown track.", status=404)
        if is_frozen(self.cfg.paths):
            raise ControlError("The event budget is frozen.", status=409)
        lock = self._lock_for(session_id)
        if not lock.acquire(blocking=False):
            raise ControlError("Still working on the previous request.", status=409)
        try:
            budget = owner_intake_budget(self.cfg, owner.owner_id)
            client = self._client_factory(budget)
            try:
                binding: Binding = propose_falsifiers(
                    session.draft.text, track, client=client, model=self.cfg.model,
                    budget=budget,
                )
            except BudgetExhausted as e:
                raise ControlError(
                    "Your intake budget is used up; the lab can still be created "
                    "without machine-checkable falsifiers.", status=402,
                ) from e
            session.track_id = track.id
            session.binding = binding.to_dict()
            session.state = "bound"
            self._save(session)
            write_event(self.cfg.paths, "bound", owner_id=owner.owner_id,
                        session_id=session_id, track=track.id,
                        n_rules=len(binding.falsifiers))
            return self.payload(session)
        finally:
            if "budget" in locals():
                budget.release()
            lock.release()

    def route(self, owner: Owner, session_id: str) -> dict:
        """Automatically reuse a compatible executor or require a new local lab."""
        session = self._load(owner, session_id)
        if session.state == "bound":
            return self.payload(session)
        if session.state != "approved":
            raise ControlError("Approve the hypothesis before routing it.", status=409)
        if is_frozen(self.cfg.paths):
            raise ControlError("The event budget is frozen.", status=409)
        lock = self._lock_for(session_id)
        if not lock.acquire(blocking=False):
            raise ControlError("Still working on the previous request.", status=409)
        try:
            budget = owner_intake_budget(self.cfg, owner.owner_id)
            client = self._client_factory(budget)
            try:
                decision = select_track(
                    session.draft.text, self.tracks, client=client,
                    model=self.cfg.model, budget=budget,
                )
            except BudgetExhausted as exc:
                raise ControlError(
                    "Your intake budget is used up; automatic routing could not finish.",
                    status=402,
                ) from exc
            session.routing = decision
            if decision["action"] == "existing":
                track = self.tracks[decision["track_id"]]
                try:
                    binding = propose_falsifiers(
                        session.draft.text, track, client=client,
                        model=self.cfg.model, budget=budget,
                    )
                except BudgetExhausted as exc:
                    raise ControlError(
                        "Your intake budget is used up; executor mapping could not finish.",
                        status=402,
                    ) from exc
                session.track_id = track.id
                session.binding = binding.to_dict()
                session.state = "bound"
            self._save(session)
            write_event(
                self.cfg.paths, "intake_routed", owner_id=owner.owner_id,
                session_id=session_id, action=decision["action"],
                track=decision.get("track_id"), confidence=decision.get("confidence"),
            )
            return self.payload(session)
        finally:
            if "budget" in locals():
                budget.release()
            lock.release()

    def mark_created(self, owner: Owner, session_id: str, lab_id: str) -> Session:
        session = self._load(owner, session_id)
        session.lab_id = lab_id
        session.state = "created"
        self._save(session)
        return session

    def design_notes(self, session: Session) -> str:
        binding = session.binding or {}
        lines = [
            f"- Web popper dialogue: {session.user_turns} participant turn(s), "
            f"validator attempts {session.draft.validator_attempts}.",
            f"- Track: {session.track_id}.",
        ]
        if binding.get("falsifiers"):
            lines.append("- Falsifiers mapped onto the track: "
                         + "; ".join(binding.get("rules_text") or []))
        if binding.get("rationale"):
            lines.append(f"- Mapping rationale: {binding['rationale']}")
        if binding.get("note"):
            lines.append(f"- Note: {binding['note']}")
        return "\n".join(lines)

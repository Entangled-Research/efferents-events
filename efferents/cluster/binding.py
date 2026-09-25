"""Route a gated hypothesis to a compatible track and map its falsifier."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from efferents.agents.popper_gate import _extract_text
from efferents.agents.state import parse_json_loose
from efferents.cluster.budget import DualBudget, usage_from_response
from efferents.cluster.tracks import Track
from efferents.dashboard.reader import _rule_text
from efferents.lab import SubmissionError, _parse_falsifiers

FALSIFIER_GRAMMAR = """\
You translate a falsifiable hypothesis into machine-checkable abandonment rules
for an automated experiment runner. Output JSON only, shaped exactly:

{"falsifiers": [ {"id": "F1", "description": "...", "when": {...}}, ... ],
 "rationale": "one paragraph",
 "lab_id": "kebab-case-suggestion"}

`when` is either an AGGREGATE rule over one ledger column:
  {"column": <column>, "agg": <median|mean|min|max|count|frac_ge|frac_le>,
   "op": <"<"|"<="|">"|">="|"=="|"!=">, "value": <number>,
   "bucket": <"any"|"all"|one bucket value>, "min_n": <int, default 3>,
   "threshold": <number, only for frac_ge/frac_le>}
or a PAIRED rule (seed-paired bootstrap CI of the median delta):
  {"column": <per-run delta column>, "ci95_excludes_zero": false}
  {"metric": <metric differenced across the two comparison arms>, "ci95_excludes_zero": false}

Rules must use only the columns the track reports. A rule FIRES when its
condition holds; a fired rule means the hypothesis is falsified. Encode the
hypothesis's own falsifier(s), not generic sanity checks. Prefer one or two
rules. Never encode missing coverage, failed API calls, invalid output or failed
source retrieval as scientific falsification. Those are metrics.constraints
preconditions; an incomplete test remains undecided. min_n counts ledger rows,
not cases within a run. Do not map a formal-proof claim to a numerical proxy.
If the hypothesis truly cannot be expressed over these columns, return
{"falsifiers": [], "rationale": "why", "lab_id": "..."}.
"""


@dataclass
class Binding:
    track_id: str
    falsifiers: list[dict] = field(default_factory=list)
    rules_text: list[str] = field(default_factory=list)
    rationale: str = ""
    lab_id_suggestion: str | None = None
    validated: bool = False
    errors: str = ""
    attempts: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


UNDECIDED_NOTE = (
    "No machine-checkable falsifier could be mapped onto this track; the "
    "verdict panel will stay undecided until one is added."
)

TRACK_ROUTER_GRAMMAR = """\
You route a research hypothesis to an existing executable experiment track only
when that track can actually run the required experiment and report metrics that
could falsify the claim. Topic resemblance is insufficient. A track for a
different dataset, scientific domain, intervention, or outcome is incompatible.
When no track is compatible, choose `new`; a coding harness will build a new lab
and executor on the participant's laptop.

Return JSON only:
{"action":"existing","track_id":"exact-id","confidence":0.0,"reason":"short"}
or
{"action":"new","track_id":null,"confidence":0.0,"reason":"short"}
"""


def select_track(
    hypothesis_text: str,
    tracks: dict[str, Track],
    *,
    client: Any,
    model: str,
    budget: DualBudget | None = None,
    max_tokens: int = 500,
) -> dict:
    """Choose a compatible executor conservatively; uncertainty creates a new one."""
    if not tracks:
        return {
            "action": "new", "track_id": None, "confidence": 1.0,
            "reason": "No compatible executor tracks are configured.",
        }
    catalogue = "\n\n".join(t.catalogue_text() for t in tracks.values())
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=TRACK_ROUTER_GRAMMAR + "\n\nAvailable tracks:\n\n" + catalogue,
        messages=[{"role": "user", "content": "Approved hypothesis:\n\n" + hypothesis_text}],
    )
    if budget is not None:
        budget.record(agent="track_router", model=model,
                      usage=usage_from_response(response), notes="automatic executor routing")
    text = _extract_text(response)
    try:
        data = parse_json_loose(text, must_contain='"action"')
    except (json.JSONDecodeError, ValueError):
        return {
            "action": "new", "track_id": None, "confidence": 0.0,
            "reason": "The compatibility check was inconclusive, so a new executor is required.",
        }
    confidence = data.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    track_id = str(data.get("track_id") or "")
    if data.get("action") == "existing" and track_id in tracks and confidence >= 0.85:
        return {
            "action": "existing", "track_id": track_id,
            "confidence": confidence, "reason": str(data.get("reason") or "")[:1000],
        }
    return {
        "action": "new", "track_id": None, "confidence": confidence,
        "reason": str(data.get("reason") or "No high-confidence compatible executor exists.")[:1000],
    }


def _render_track(track: Track) -> str:
    payload = track.payload()
    if track.example_falsifiers:
        payload["example_falsifiers"] = list(track.example_falsifiers)
    return json.dumps(payload, indent=2)


def propose_falsifiers(
    hypothesis_text: str,
    track: Track,
    *,
    client: Any,
    model: str,
    budget: DualBudget | None = None,
    max_tokens: int = 1200,
) -> Binding:
    """One headless call (plus one retry on validation errors)."""
    binding = Binding(track_id=track.id)
    system = FALSIFIER_GRAMMAR + "\n\nTrack description:\n" + _render_track(track)
    messages = [{"role": "user", "content": f"Hypothesis file:\n\n{hypothesis_text}"}]
    last_error = ""
    for attempt in (1, 2):
        binding.attempts = attempt
        if attempt == 2:
            messages = messages + [
                {"role": "user", "content": (
                    "The previous rules failed validation with:\n\n" + last_error +
                    "\n\nReturn corrected JSON only."
                )},
            ]
        response = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages,
        )
        if budget is not None:
            budget.record(agent="falsifier_binding", model=model,
                          usage=usage_from_response(response), notes=f"attempt={attempt}")
        text = _extract_text(response)
        try:
            data = parse_json_loose(text, must_contain='"falsifiers"')
        except json.JSONDecodeError as e:
            last_error = f"not valid JSON: {e}"
            messages = messages + [{"role": "assistant", "content": text}]
            continue
        rules = data.get("falsifiers") or []
        binding.rationale = str(data.get("rationale") or "").strip()
        suggestion = data.get("lab_id")
        binding.lab_id_suggestion = str(suggestion).strip() if suggestion else None
        try:
            parsed = _parse_falsifiers(rules, track.bucket_axes)
        except SubmissionError as e:
            last_error = str(e)
            messages = messages + [{"role": "assistant", "content": text}]
            continue
        known = {c["name"] for c in track.columns}
        unknown = [
            r for r in parsed
            if known and (r.column or r.metric) not in known
        ]
        if unknown:
            last_error = (
                "rules reference columns the track does not report: "
                + ", ".join(r.column or r.metric for r in unknown)
            )
            messages = messages + [{"role": "assistant", "content": text}]
            continue
        binding.falsifiers = [dict(r) for r in rules]
        binding.rules_text = [_rule_text(r) for r in parsed]
        binding.validated = True
        binding.errors = ""
        if not parsed:
            binding.note = UNDECIDED_NOTE
        return binding
    binding.validated = False
    binding.errors = last_error
    binding.falsifiers = []
    binding.rules_text = []
    binding.note = UNDECIDED_NOTE
    return binding

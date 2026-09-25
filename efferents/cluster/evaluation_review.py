"""Operator review annotations bound to an exact preserved telemetry snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint(raw: bytes) -> str:
    document = json.loads(raw)
    document.pop('synced_at', None)
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def review(directory: Path) -> dict:
    try:
        note = json.loads((directory / 'evaluation-review.json').read_text())
        raw = (directory / 'owner-evals.json').read_bytes()
    except (OSError, ValueError):
        return {}
    if note.get('snapshot_sha256') != fingerprint(raw):
        return {}
    return note


def annotate(directory: Path, view: dict, *, idea_id: str = 'primary') -> dict:
    note = review(directory).get('ideas', {}).get(idea_id)
    if not isinstance(note, dict) or not note.get('reason'):
        return view
    reason = str(note['reason'])
    view['evaluation_review'] = note
    verdict = view.setdefault('verdict', {})
    verdict.update(verdict='undecided', status='undecided', line='Evaluation needs repair: ' + reason)
    for rule in verdict.get('falsifiers', []):
        rule.update(reported_status=rule.get('status'), status='insufficient_data', detail=reason)
    if isinstance(view.get('suite'), dict):
        view['suite']['message'] = reason
    return view

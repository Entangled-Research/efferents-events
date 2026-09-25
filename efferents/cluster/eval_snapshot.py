"""Bounded participant-visible console telemetry. Never included in journal/agent feeds."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

MAX_SNAPSHOT = 850_000
MAX_IMAGE = 180_000


def build(lab_root: Path, cfg) -> dict:
    from efferents.dashboard import reader
    evidence, catalog = reader._evidence_payload(lab_root, cfg)
    evidence = copy.deepcopy(evidence)
    records, images, seen = [], {}, set()
    artifact_map = {}
    seen_runs = set()
    for record in evidence['records']:
        if record['run_id'] in seen_runs:
            continue
        seen_runs.add(record['run_id'])
        artifacts = []
        for artifact in record.get('artifacts', []):
            path = catalog.get(artifact.get('token'))
            if path is None or path.suffix.lower() != '.png' or path.stat().st_size > MAX_IMAGE:
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            key = (record['run_id'], digest)
            if key in seen:
                continue
            if sum(len(v) for v in images.values()) + len(raw) * 4 // 3 > 450_000:
                continue
            seen.add(key)
            images[digest] = base64.b64encode(raw).decode()
            packed = {'kind': artifact.get('kind', 'image'), 'token': digest,
                      'url': f'/api/labs/{cfg.lab_id}/artifacts/{digest}'}
            artifacts.append(packed)
            artifact_map[(record['run_id'], artifact['token'])] = packed
        records.append({**record, 'artifacts': artifacts})
        if len(records) >= 12:
            break
    evidence['records'] = records
    evidence['artifact_count'] = sum(len(r['artifacts']) for r in records)
    result = {'runs': reader.read_runs(lab_root, n=60, cfg=cfg),
              'evidence': evidence, 'verdict': reader.read_verdict(lab_root, cfg),
              'images': images}
    from efferents.dashboard.ideas import read_idea
    result['ideas'] = {}
    from efferents.lifecycle import inactive
    for student in cfg.students:
        if inactive(lab_root, student['id']):
            continue
        view = read_idea(lab_root, cfg, student['id'])
        # Reuse already-bounded, hashed images for the same run. No image or
        # unscoped evidence from a sibling idea is introduced into the view.
        scoped_records = []
        scoped_seen = set()
        for record in view['evidence']['records']:
            if record['run_id'] in scoped_seen:
                continue
            scoped_seen.add(record['run_id'])
            artifacts = [artifact_map[(record['run_id'], a['token'])]
                         for a in record['artifacts'] if (record['run_id'], a['token']) in artifact_map]
            scoped_records.append({**record, 'artifacts': artifacts})
        view['evidence']['records'] = scoped_records[:12]
        view['evidence']['artifact_count'] = sum(len(record['artifacts']) for record in view['evidence']['records'])
        result['ideas'][student['id']] = view
    if len(json.dumps(result).encode()) > MAX_SNAPSHOT:
        raise ValueError('Owner eval snapshot exceeds byte limit')
    return result


def validate(raw: object, lab_id: str) -> dict:
    if not isinstance(raw, dict) or len(json.dumps(raw, allow_nan=False).encode()) > MAX_SNAPSHOT:
        raise ValueError('Invalid owner eval snapshot size')
    result = {key: copy.deepcopy(raw.get(key, {})) for key in ('runs', 'evidence', 'verdict')}
    if not all(isinstance(v, dict) for v in result.values()):
        raise ValueError('Eval views must be objects')
    images = raw.get('images', {})
    if not isinstance(images, dict) or len(images) > 12:
        raise ValueError('Too many eval images')
    verified = {}
    for digest, encoded in images.items():
        if not isinstance(encoded, str):
            raise ValueError('Invalid image')
        image = base64.b64decode(encoded, validate=True)
        if len(image) > MAX_IMAGE or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Only bounded PNG images are accepted')
        if hashlib.sha256(image).hexdigest() != digest:
            raise ValueError('Eval image digest mismatch')
        verified[digest] = encoded
    records = result['evidence'].get('records', [])
    if not isinstance(records, list) or len(records) > 12:
        raise ValueError('Too many eval records')
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('artifacts', []), list):
            raise ValueError('Invalid eval record')
        record['artifacts'] = [
            {'kind': str(a.get('kind', 'image'))[:80], 'token': a['token'],
             'url': f'/api/labs/{lab_id}/artifacts/{a["token"]}'}
            for a in record.get('artifacts', [])
            if isinstance(a, dict) and isinstance(a.get('token'), str) and a['token'] in verified]
    ideas = raw.get('ideas', {})
    if not isinstance(ideas, dict) or len(ideas) > 100:
        raise ValueError('Invalid idea eval map')
    result['ideas'] = {}
    for student_id, view in ideas.items():
        if not isinstance(view, dict) or view.get('student_id') != student_id:
            raise ValueError('Idea eval identity mismatch')
        # Recursive sanitization applies the same image URL restrictions to
        # each idea as to the legacy default-idea snapshot.
        clean = validate({**{k: view.get(k, {}) for k in ('runs', 'evidence', 'verdict')}, 'images': verified}, lab_id)
        metadata = {k: copy.deepcopy(view.get(k)) for k in ('student_id', 'name', 'focus', 'hypothesis', 'campaign_ids', 'suite')}
        if not isinstance(metadata['suite'], dict) or not isinstance(metadata['hypothesis'], dict):
            raise ValueError('Invalid idea metadata')
        result['ideas'][student_id] = {**metadata, **{k: clean[k] for k in ('runs', 'evidence', 'verdict')}}
    result['images'] = verified
    return result

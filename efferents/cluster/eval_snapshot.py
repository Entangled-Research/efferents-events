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
    for record in evidence['records']:
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
            artifacts.append({'kind': artifact.get('kind', 'image'), 'token': digest,
                              'url': f'/api/labs/{cfg.lab_id}/artifacts/{digest}'})
        if artifacts:
            records.append({**record, 'artifacts': artifacts})
        if len(records) >= 12:
            break
    evidence['records'] = records
    evidence['artifact_count'] = sum(len(r['artifacts']) for r in records)
    result = {'runs': reader.read_runs(lab_root, n=60, cfg=cfg),
              'evidence': evidence, 'verdict': reader.read_verdict(lab_root, cfg),
              'images': images}
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
    result['images'] = verified
    return result

import base64
import hashlib

import pytest

from efferents.cluster.eval_snapshot import validate
from tests.test_cluster_network import hub, _bearer  # noqa: F401
from tests.test_cluster_server import _join, _request
from tests.cluster_helpers import VALID_HYP


def snapshot():
    raw = b'\x89PNG\r\n\x1a\nexample'
    digest = hashlib.sha256(raw).hexdigest()
    return {'runs': {'runs': [{'run_id': 'private-run'}]},
            'evidence': {'records': [{'artifacts': [{'kind': 'sample', 'token': digest,
                                                   'url': 'https://untrusted.example/'}]}]},
            'verdict': {}, 'images': {digest: base64.b64encode(raw).decode()}}


def test_snapshot_validates_images_and_rewrites_urls():
    data = snapshot()
    result = validate(data, 'my-lab')
    assert result['evidence']['records'][0]['artifacts'][0]['url'].startswith('/api/labs/my-lab/artifacts/')
    data['images']['forged'] = next(iter(data['images'].values()))
    with pytest.raises(ValueError, match='digest'):
        validate(data, 'my-lab')
    with pytest.raises(ValueError):
        validate({'runs': {'value': float('nan')}}, 'my-lab')


def test_participant_eval_views_and_owner_only_mutations(hub):  # noqa: F811
    port, ctx, *_ = hub
    ada, _ = _join(port, 'Ada')
    bob, _ = _join(port, 'Bob')
    auth = _bearer(ada)
    status, _, _ = _request(port, '/api/network/labs', method='POST', headers=auth,
                            payload={'lab_id': 'qml', 'domain': 'qml', 'hypothesis': VALID_HYP})
    assert status == 200
    data = snapshot()
    status, _, _ = _request(port, '/api/network/labs/qml/heartbeat', method='POST', headers=auth,
                            payload={'owner_evals': data})
    assert status == 200
    _, own, _ = _request(port, '/api/labs/qml/runs', headers=auth)
    _, other, _ = _request(port, '/api/labs/qml/runs', headers=_bearer(bob))
    assert own['runs'] == [{'run_id': 'private-run'}]
    assert other['runs'] == own['runs']
    _, evidence, _ = _request(port, '/api/labs/qml/evidence', headers=_bearer(bob))
    assert evidence['records']
    assert _request(port, '/api/labs/qml/runs')[0] == 401
    assert _request(port, '/api/labs/qml/evidence')[0] == 401
    assert _request(port, '/api/network/labs/qml/heartbeat', method='POST',
                    headers=_bearer(bob), payload={'owner_evals': data})[0] == 403
    digest = next(iter(data['images']))
    status, _, _ = _request(port, '/api/labs/qml/artifacts/' + digest, headers=_bearer(bob))
    assert status == 200
    status, _, _ = _request(port, '/api/labs/qml/artifacts/' + digest, headers=auth)
    assert status == 200
    status, _, _ = _request(port, '/api/labs/qml/artifacts/' + digest)
    assert status == 401
    assert 'private-run' not in ctx.hub.feed()


def test_tested_wheel_is_authenticated_and_hash_pinned(hub, tmp_path, monkeypatch):  # noqa: F811
    port, *_ = hub
    wheel = tmp_path / 'efferents-0.1.4-py3-none-any.whl'
    wheel.write_bytes(b'tested wheel fixture')
    monkeypatch.setenv('EFFERENTS_INSTALL_WHEEL', str(wheel))
    owner, _ = _join(port, 'Installer')
    auth = _bearer(owner)
    status, config, _ = _request(port, '/api/network/config', headers=auth)
    assert status == 200
    assert config['install']['sha256'] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert config['env']['EFFERENTS_GENERATE_EVAL_SUITE'] == '1'
    assert config['env']['EFFERENTS_OWNER_EVAL_SYNC'] == '1'
    status, _, _ = _request(port, '/api/network/package')
    assert status == 401
    status, body, _ = _request(port, '/api/network/package', headers=auth)
    assert status == 200 and body['raw'] == 'tested wheel fixture'


def test_snapshot_keeps_numeric_rows_without_images_and_deduplicates(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from efferents.cluster.eval_snapshot import build
    from efferents.dashboard import reader
    row = {'run_id': 'numeric', 'metrics': {'score': 3}, 'artifacts': []}
    monkeypatch.setattr(reader, '_evidence_payload', lambda *a: ({'records': [row, row]}, {}))
    monkeypatch.setattr(reader, 'read_runs', lambda *a, **kw: {})
    monkeypatch.setattr(reader, 'read_verdict', lambda *a: {})
    result = build(tmp_path, SimpleNamespace(lab_id='test', students=[]))
    assert result['evidence']['records'] == [row]
    assert result['evidence']['artifact_count'] == 0


def test_review_annotation_never_overrides_new_evidence(tmp_path):
    import json
    from efferents.cluster.evaluation_review import annotate
    raw = b'{"runs": {}}'
    (tmp_path / 'owner-evals.json').write_bytes(raw)
    (tmp_path / 'evaluation-review.json').write_text(json.dumps({
        'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
        'ideas': {'primary': {'reason': 'One case of 100; model call failed'}}}))
    assert annotate(tmp_path, {'verdict': {'verdict': 'falsified'}})['verdict']['verdict'] == 'undecided'
    (tmp_path / 'owner-evals.json').write_text('{"runs": {"new": true}}')
    assert annotate(tmp_path, {'verdict': {'verdict': 'falsified'}})['verdict']['verdict'] == 'falsified'

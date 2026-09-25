import json
import pytest
from efferents.cluster.remote_control import apply_commands, command_acks
from efferents.lifecycle import inactive
from tests.test_cluster_network import hub, _bearer  # noqa: F401
from tests.test_cluster_server import _join, _request
from tests.cluster_helpers import VALID_HYP


def setup_lab(port):
    ada, _ = _join(port, 'Ada')
    bob, _ = _join(port, 'Bob')
    auth = _bearer(ada)
    assert _request(port, '/api/network/labs', method='POST', headers=auth,
                    payload={'lab_id': 'owned', 'domain': 'math', 'hypothesis': VALID_HYP})[0] == 200
    _request(port, '/api/network/labs/owned/heartbeat', method='POST', headers=auth,
             payload={'ideas': [{'id': 'primary'}, {'id': 'second'}], 'runs': 3})
    return ada, bob, auth


@pytest.mark.parametrize('action,payload', [('delete', {}), ('deleteidea', {'idea_id': 'primary'})])
def test_only_owner_can_delete_and_confirmation_required(hub, action, payload):  # noqa: F811
    port, ctx, *_ = hub
    ada, bob, auth = setup_lab(port)
    endpoint = '/api/network/labs/owned/' + action
    assert _request(port, endpoint, method='POST', payload={'confirmed': True, **payload})[0] == 403
    assert _request(port, endpoint, method='POST', headers=_bearer(bob), payload={'confirmed': True, **payload})[0] == 403
    assert _request(port, endpoint, method='POST', headers=auth, payload=payload)[0] == 400
    directory = ctx.hub.lab_dir('owned')
    before = (directory / 'heartbeat.json').read_bytes()
    assert _request(port, endpoint, method='POST', headers=auth, payload={'confirmed': True, **payload})[0] == 200
    assert (directory / 'heartbeat.json').read_bytes() == before
    assert (directory / 'hypothesis.md').read_text() == VALID_HYP
    assert _request(port, endpoint, method='POST', headers=auth, payload={'confirmed': True, **payload})[0] == 200
    if action == 'delete':
        assert not ctx.hub.portfolio_rows()
        reply = _request(port, '/api/network/labs/owned/heartbeat', method='POST', headers=auth, payload={'runs': 99})[1]
        assert reply['pause'] and reply['deleted']
        assert (directory / 'heartbeat.json').read_bytes() == before
        assert _request(port, '/api/network/labs', method='POST', headers=auth,
                         payload={'lab_id': 'owned', 'hypothesis': VALID_HYP})[0] == 409
        assert _request(port, '/api/labs/owned/control', headers=auth)[0] == 410
    else:
        assert [i['id'] for i in ctx.hub.portfolio_rows()[0]['ideas']] == ['second']
        assert _request(port, '/api/labs/owned/ideas/primary', headers=auth)[0] == 410
        _request(port, '/api/network/labs/owned/heartbeat', method='POST', headers=auth,
                 payload={'ideas': [{'id': 'primary'}, {'id': 'second'}]})
        assert [i['id'] for i in ctx.hub.portfolio_rows()[0]['ideas']] == ['second']
        assert len(json.loads((directory / 'commands.json').read_text())) == 1


def test_idea_deletion_delivered_once_and_pause_until_ack(hub, tmp_path):  # noqa: F811
    port, ctx, *_ = hub
    _, _, auth = setup_lab(port)
    _request(port, '/api/network/labs/owned/deleteidea', method='POST', headers=auth,
             payload={'confirmed': True, 'idea_id': 'primary'})
    endpoint = '/api/network/labs/owned/heartbeat'
    reply = _request(port, endpoint, method='POST', headers=auth, payload={})[1]
    assert reply['pause']
    from efferents import steer
    root = tmp_path / 'participant' / 'lab'
    apply_commands(root.parent, root, reply['commands'])
    apply_commands(root.parent, root, reply['commands'])
    assert inactive(root, 'primary') and not inactive(root, 'second')
    assert len(steer.read_steering(root)) == 1
    reply = _request(port, endpoint, method='POST', headers=auth,
                     payload={'command_acks': command_acks(root)})[1]
    assert not reply['pause'] and not reply['commands']


def test_setup_failures_are_owner_scoped_and_credential_free(hub):  # noqa: F811
    port, ctx, *_ = hub
    ada, bob, auth = setup_lab(port)
    assert _request(port, '/api/network/config', headers=auth)[0] == 200
    assert _request(port, '/api/network/labs', method='POST', headers=auth,
                    payload={'lab_id': 'broken', 'hypothesis': ''})[0] == 400
    report = _request(port, '/api/diagnostics', headers=auth)[1]
    assert any(e.get('stage') == 'config_download' for e in report['recent_setup_events'])
    assert any(e.get('stage') == 'registration' and e['status'] == 400 for e in report['recent_setup_events'])
    other = _request(port, '/api/diagnostics', headers=_bearer(bob))[1]
    assert not other['recent_setup_events']
    assert ada['cluster']['network_token'] not in json.dumps(report)


def test_browser_delete_requires_csrf_even_for_owner(hub):  # noqa: F811
    port, *_ = hub
    _, _, auth = setup_lab(port)
    token = auth['Authorization'].removeprefix('Bearer ')
    from efferents.cluster.owners import build_cookie
    cookie = build_cookie(token, max_age_s=3600, secure=False).split(';')[0]
    assert _request(port, '/api/labs/owned/delete', method='POST', headers={'Cookie': cookie},
                    payload={'confirmed': True})[0] == 403

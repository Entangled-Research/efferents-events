import json
import shutil
from pathlib import Path

import pytest
import yaml

from efferents.cluster.remote_control import apply_commands, command_acks, pending_commands, queue_command
from efferents.dashboard.control import ControlError
from efferents.lab import LabConfig
from tests.cluster_helpers import VALID_HYP
from tests.test_cluster_network import _bearer

from tests.test_cluster_server import _join, _request

pytest_plugins = ["tests.test_cluster_network"]


def decision(action='create', lab_id=None, broad=False, domain='quantum graph learning'):
    return json.dumps({'action': action, 'lab_id': lab_id, 'domain': domain,
                      'objective': 'Develop the best quantum GNN', 'broad': broad,
                      'confidence': .98, 'reason': 'Distinct graph-learning objective',
                      'ideas': [{'title': name, 'focus': 'Compare fixed splits, baseline and five seeds; reject a nonpositive accuracy margin.'}
                                for name in (['Graph entanglers', 'Node encoding', 'Circuit depth'] if broad else ['Graph entanglers'])]})


def submit(port, auth, text='Develop the best quantum GNN', key='request-123'):
    return _request(port, '/api/network/submissions', method='POST', headers=auth,
                    payload={'text': text, 'request_id': key})


def test_broad_qgnn_is_separate_lab_in_same_quantum_journal(hub):
    port, ctx, scripts, *_ = hub
    joined, auth = _join(port)
    _request(port, '/api/network/labs', method='POST', headers=_bearer(joined),
             payload={'lab_id': 'encoding', 'domain': 'quantum encoding', 'hypothesis': VALID_HYP})
    scripts['replies'].append(decision(broad=True))
    status, result, _ = submit(port, auth)
    assert status == 200, result
    assert result['action'] == 'create' and result['lab_id'] is None
    assert result['journal'] == ctx.hub.portfolio_rows()[0]['journal'] == 'Physics & Dynamics'
    assert len(result['ideas']) == 3 and result['status'] == 'ready_for_setup'
    assert len(ctx.hub.list_labs()) == 1  # no daemon or paid experiments launched
    assert not (ctx.hub.lab_dir('encoding') / 'commands.json').exists()
    status, repeat, _ = submit(port, auth)
    assert status == 200 and repeat == result and not scripts['replies']
    stranger, stranger_auth = _join(port, 'Bob')
    status, _, _ = _request(port, '/api/network/submissions/' + result['id'], headers=stranger_auth)
    assert status == 404
    status, saved, _ = _request(port, '/api/network/submissions/' + result['id'], headers=auth)
    assert status == 200 and saved == result


def test_new_math_field_and_uncertain_placement_create(hub):
    port, _, scripts, *_ = hub
    _, auth = _join(port)
    data = json.loads(decision(action='append', lab_id='nonexistent', domain='mathematics'))
    data['confidence'] = .3
    scripts['replies'].append(json.dumps(data))
    status, result, _ = submit(port, auth, text='Prove a graph bound')
    assert status == 200 and result['action'] == 'create'
    assert result['journal'] == 'Mathematics & Computation'


def test_cross_participant_contribution_is_durable_idempotent_and_preserves_controls(hub, tmp_path):
    port, ctx, scripts, *_ = hub
    joined, _ = _join(port, 'Ada')
    auth = _bearer(joined)
    _request(port, '/api/network/labs', method='POST', headers=auth,
             payload={'lab_id': 'qgnn', 'domain': 'quantum graph learning', 'hypothesis': VALID_HYP})
    bob, bob_auth = _join(port, 'Bob')
    scripts['replies'].append(decision('append', 'qgnn'))
    status, result, _ = submit(port, bob_auth, text='Compare graph entanglers with no entanglers')
    assert status == 200 and result['action'] == 'append', result
    owner = ctx.owners.by_token(joined['cluster']['network_token'])
    other = ctx.owners.by_token(bob['cluster']['network_token'])
    with pytest.raises(ControlError):
        queue_command(ctx.hub, other, 'qgnn', 'resume', {})
    queue_command(ctx.hub, owner, 'qgnn', 'pause', {})
    pending = pending_commands(ctx.hub, owner, 'qgnn', {})
    assert pending[0]['action'] == 'contribute'
    assert pending[0]['owner_id'] == other.owner_id
    source = Path(__file__).resolve().parents[1] / 'examples' / 'smoke-lab'
    local = tmp_path / 'local-qgnn'
    shutil.copytree(source, local)
    root = local / 'lab'
    root.mkdir(exist_ok=True)
    (root / 'evidence.json').write_text('{"runs":42}')
    before = yaml.safe_load((local / 'lab.yaml').read_text())
    apply_commands(local, root, pending)
    apply_commands(local, root, pending)
    after = yaml.safe_load((local / 'lab.yaml').read_text())
    assert len(after['students']) == len(before.get('students') or [{}]) + 1
    assert after.get('budget') == before.get('budget')
    assert (root / 'evidence.json').read_text() == '{"runs":42}'
    assert len(command_acks(root)) == 2
    assert pending_commands(ctx.hub, owner, 'qgnn', {'command_acks': command_acks(root)}) == []
    assert ctx.hub.registration('qgnn')['owner_id'] == owner.owner_id
    assert LabConfig.from_submission(local).students[-1]['handle'] == 'Graph entanglers'


def test_invalid_submission_is_free_and_authentication_required(hub):
    port, _, scripts, *_ = hub
    status, _, _ = submit(port, {})
    assert status in {401, 403}  # unauthenticated cookie requests fail CSRF first
    _, auth = _join(port)
    status, _, _ = submit(port, auth, text='')
    assert status == 400 and not scripts['replies']


def test_inconclusive_routing_saves_original_and_hands_off_without_repeat_charge(hub):
    port,ctx,scripts,*_=hub
    _,auth=_join(port)
    scripts['replies'].append('{"action":"create","broad":true,"ideas":[]}')
    original='Research the best graph neural network without dropping my objective.'
    status,result,_=submit(port,auth,text=original)
    assert status==200 and result['needs_refinement'] and result['text']==original
    assert result['request_id']=='request-123' and result['status']=='ready_for_setup'
    first=(ctx.cfg.paths.intake/'budget.jsonl').read_text()
    assert submit(port,auth,text=original)[1]==result
    assert (ctx.cfg.paths.intake/'budget.jsonl').read_text()==first
    status,items,_=_request(port,'/api/network/submissions',headers=auth)
    assert status==200 and items[0]['id']==result['id']
    _,other=_join(port,'Bob')
    assert _request(port,'/api/network/submissions',headers=other)[1]==[]


def test_timeout_keeps_input_and_uncertain_hold(hub):
    from efferents.cluster.budget import coordinator
    port,ctx,*_=hub
    _,auth=_join(port)
    class BrokenClient:
        def __init__(self,budget):
            self.budget=budget
            self.messages=self
        def create(self,**kwargs):
            self.budget.reserve(kwargs['model'],kwargs['max_tokens'],100)
            raise TimeoutError('unknown provider result')
    ctx.intake._client_factory=BrokenClient
    status,result,_=submit(port,auth,text='Keep this question through a provider timeout.')
    assert status==200 and result['needs_refinement']
    assert result['text']=='Keep this question through a provider timeout.'
    assert len(coordinator(ctx.cfg).reservations())==1


def test_slow_submission_does_not_block_other_participants(hub):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from tests.cluster_helpers import ScriptedClient
    _,ctx,*_=hub
    alice,bob=ctx.owners.join('Slow'),ctx.owners.join('Fast')
    entered,release=threading.Event(),threading.Event()
    class Client(ScriptedClient):
        def create(self,**kwargs):
            if self.budget.owner_id==alice.owner_id:
                entered.set()
                release.wait(3)
            return super().create(**kwargs)
    ctx.intake._client_factory=lambda budget:Client([decision()],budget=budget)
    payload={'text':'A research objective','request_id':'parallel-request'}
    with ThreadPoolExecutor(2) as pool:
        slow=pool.submit(ctx.submissions.submit,alice,payload)
        try:
            assert entered.wait(1)
            fast=pool.submit(ctx.submissions.submit,bob,payload)
            assert fast.result(timeout=1)['action']=='create'
            assert not slow.done()
        finally:
            release.set()
        assert slow.result()['action']=='create'


def test_long_question_preserved_and_broad_fluorescence_routes_to_existing_lab(hub):
    port, ctx, scripts, *_ = hub
    joined, _ = _join(port, 'Existing researcher')
    _request(port, '/api/network/labs', method='POST', headers=_bearer(joined),
             payload={'lab_id': 'gfp', 'domain': 'GFP fluorescence prediction', 'hypothesis': VALID_HYP})
    _, auth = _join(port, 'Contributor')
    original = ('Predict protein fluorescence. ' + 'Preserve these research details. ' * 2000).strip()
    data = json.loads(decision('append', 'gfp', broad=True, domain='GFP fluorescence prediction'))
    data['objective'] = original
    data['ideas'][0]['focus'] = original
    scripts['replies'].append(json.dumps(data))
    status, result, _ = submit(port, auth, original)
    assert status == 200 and result['action'] == 'append', result
    assert result['lab_id'] == 'gfp' and result['text'] == original
    assert result['objective'] == original and result['ideas'][0]['focus'] == original
    assert len(result['ideas']) == 3
    commands = json.loads((ctx.hub.lab_dir('gfp') / 'commands.json').read_text())
    assert commands[0]['text'] == original

"""The paid rehearsal must reserve one aggregate cap before concurrent calls."""
from concurrent.futures import ThreadPoolExecutor

from deploy.events.oct24.rehearsal.guard import Guard


def test_shared_cap_reserves_concurrent_calls_and_survives_restart(tmp_path):
    guard = Guard(tmp_path, 'https://event.test', 'private', .5)
    def reserve(_):
        try:
            return guard.reserve('openai/gpt-6.1-sol', 10000, 300, 'lab')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = [value for value in pool.map(reserve, range(12)) if value]
    assert len(accepted) == 4
    assert guard.state()['remaining'] >= 0
    restored = Guard(tmp_path, 'https://event.test', 'private', .5)
    assert restored.state() == guard.state()
    restored.settle(accepted[0], 'openai/gpt-6.1-sol', {'usage':{
        'input_tokens':100, 'output_tokens':20, 'input_tokens_details':{'cached_tokens':50}}}, 200, 'lab')
    assert restored.state()['pending'] == 3
    assert abs(restored.state()['spent'] - .000305) < 1e-12
    restored.settle(accepted[1], 'openai/gpt-6.1-sol', {}, 502, 'lab')
    assert restored.state()['pending'] == 3  # Unknown billing never becomes free credit.

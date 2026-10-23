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


def test_rehearsal_results_exclude_orphans_and_failed_rows(tmp_path):
    import json
    import sqlite3
    import yaml
    from deploy.events.oct24.rehearsal.analyze import analyze
    sub=tmp_path/'lab-source'
    (sub/'lab').mkdir(parents=True)
    (tmp_path/'baseline.json').write_text(json.dumps({'labs':[{'lab_id':'masha-test','path':str(sub)}]}))
    catalogue=tmp_path/'manifest.json'
    catalogue.write_text(json.dumps([{'id':'test','config':{'task':'a','seed':0,'size':10},'ideas':[{'id':'a','task':'a','title':'test'}]}]))
    with sqlite3.connect(sub/'lab/runs.sqlite') as db:
        db.execute('CREATE TABLE campaigns (id TEXT, student_id TEXT)')
        db.execute('INSERT INTO campaigns VALUES (?,?)',('registered','a'))
        db.execute('CREATE TABLE runs (run_id TEXT, started_at TEXT, student_id TEXT, status TEXT, campaign_id TEXT, config_yaml TEXT, raw_metrics_json TEXT)')
        for seed in range(5):
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(str(seed),str(seed),'a','succeeded','registered',yaml.safe_dump({'task':'a','seed':seed,'size':10}),json.dumps({'effect':-.1})))
        for campaign,status,value in [('unknown','succeeded',999),('registered','failed',0)]:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(campaign,'9','a',status,campaign,yaml.safe_dump({'task':'a','seed':0,'size':10}),json.dumps({'effect':value})))
    result=analyze(tmp_path,catalogue)['ideas'][0]
    assert result['eligible_distinct_seeds']==5
    assert result['mean_effect']==-.1
    assert result['status']=='target_missed'
    assert result['excluded']=={'unregistered_campaign':1,'failed_or_incomplete':1}

"""Summarize real rehearsal activity; no secrets or model response content."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import urllib.request


def intervals(rows, begin, end, predicate=lambda row: True):
    active, maximum = {}, 0
    completed = []
    starts = {}
    for row in rows:
        if row['event'] == begin and predicate(row):
            active[row['id']] = row
            starts[row['id']] = row
            maximum = max(maximum, len(active))
        elif row['event'] == end and row['id'] in active:
            start = active.pop(row['id'])
            completed.append({'lab':start['lab'], 'student':start.get('student'),
                              'seconds':row['clock']-start['clock']})
    return {'peak':maximum, 'active':len(active), 'started':len(starts),
            'completed':len(completed), 'seconds':round(sum(x['seconds'] for x in completed), 2)}


def summarize(root):
    baseline = json.loads((root/'baseline.json').read_text())
    rows = [json.loads(x) for x in (root/'activity.jsonl').read_text().splitlines()]
    rows.sort(key=lambda x:x['clock'])
    port = (root/'guard-port').read_text()
    try:
        budget = json.load(urllib.request.urlopen('http://127.0.0.1:'+port+'/status',timeout=5))
    except OSError:
        budget = {'guard':'unreachable'}
    result = {'elapsed_minutes':round((datetime.now().astimezone()-datetime.fromisoformat(baseline['started_at'])).total_seconds()/60, 1),
              'budget':budget, 'researchers':intervals(rows,'begin','end',lambda r:r.get('role')=='researcher'),
              'researcher_model_calls':intervals(rows,'model_begin','model_end',lambda r:r.get('phase',{}).get('role')=='researcher'),
              'all_model_calls':intervals(rows,'model_begin','model_end'),
              'errors':[r for r in rows if r.get('ok') is False or r['event']=='worker_crash'], 'labs':[]}
    for lab in baseline['labs']:
        path = Path(lab['path'])/'lab/runs.sqlite'
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            runs = [dict(r) for r in db.execute('SELECT student_id,status,error,effect FROM runs')]
            campaigns = [dict(r) for r in db.execute('SELECT id,student_id,closed_at,close_reason FROM campaigns')]
        result['labs'].append({'lab':lab['lab_id'],'runs':len(runs),'statuses':dict(Counter(r['status'] for r in runs)),
                               'ideas':dict(Counter(r['student_id'] for r in runs)),
                               'run_errors':[r for r in runs if r['error']], 'campaigns':campaigns})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir',type=Path)
    print(json.dumps(summarize(parser.parse_args().run_dir),indent=2))

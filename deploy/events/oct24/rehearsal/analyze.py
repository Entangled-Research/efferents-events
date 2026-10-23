"""Collect preregistered seed results without reassigning historical evidence."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

import numpy as np
import yaml


def analyze(run_dir, catalogue):
    baseline = json.loads((run_dir/'baseline.json').read_text())
    manifest = json.loads(catalogue.read_text())
    rows_out, anomalies = [], []
    for lab in manifest:
        metadata = next(x for x in baseline['labs'] if x['lab_id']=='masha-'+lab['id'])
        with sqlite3.connect(Path(metadata['path'])/'lab/runs.sqlite') as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute('SELECT * FROM runs ORDER BY started_at')]
            campaigns = {row['id']:dict(row) for row in db.execute('SELECT * FROM campaigns')}
        for idea in lab['ideas']:
            required = {**lab['config'],'task':idea['task']}
            grouped = defaultdict(list)
            excluded = defaultdict(int)
            for row in rows:
                if row['student_id']!=idea['id']:
                    continue
                if row['status']!='succeeded':
                    excluded['failed_or_incomplete']+=1
                    continue
                campaign = campaigns.get(row['campaign_id'])
                if not campaign or campaign['student_id']!=idea['id']:
                    excluded['unregistered_campaign']+=1
                    anomalies.append({'lab':lab['id'],'idea':idea['id'],'run_id':row['run_id'],
                                      'reason':'Unknown or wrong-student campaign ID; raw evidence retained unchanged'})
                    continue
                config = yaml.safe_load(row['config_yaml'])
                if any(config.get(key)!=value for key,value in required.items() if key!='seed'):
                    excluded['different_protocol']+=1
                    continue
                seed = config.get('seed')
                if seed not in range(5):
                    excluded['followup_seed']+=1
                    continue
                metrics = json.loads(row['raw_metrics_json'])
                if not np.isfinite(metrics.get('effect', float('nan'))):
                    excluded['nonfinite_effect']+=1
                    continue
                grouped[seed].append({'run_id':row['run_id'],'campaign_id':row['campaign_id'],
                                      'seed':seed,'metrics':metrics})
            chosen = [grouped[seed][0] for seed in sorted(grouped)]
            effects = np.array([r['metrics']['effect'] for r in chosen])
            if len(effects)>=5:
                rng = np.random.default_rng(20261024)
                bootstrap = rng.choice(effects,(20000,len(effects)),replace=True).mean(axis=1)
                low,high = np.quantile(bootstrap,[.025,.975]).tolist()
            else:
                low=high=None
            rows_out.append({'lab':lab['id'],'idea':idea['id'],'title':idea['title'],
                             'eligible_distinct_seeds':len(chosen),'duplicate_seed_runs':sum(max(0,len(g)-1) for g in grouped.values()),
                             'mean_effect':float(effects.mean()) if len(effects) else None,
                             'mean_effect_bootstrap_95_ci':[low,high],
                             'status':'incomplete' if len(chosen)<5 else 'target_missed' if effects.mean()<0 else 'numeric_target_met',
                             'excluded':dict(excluded),'runs':chosen})
    return {'protocol':'First registered run per seed 0–4 at the frozen starter defaults; no historical run reassignment. Bootstrap intervals describe seed variation, not new-dataset generalization.',
            'ideas':rows_out,'anomalies':anomalies}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('run_dir',type=Path)
    parser.add_argument('--catalogue',type=Path,required=True)
    args=parser.parse_args()
    result=analyze(args.run_dir,args.catalogue)
    (args.run_dir/'preregistered-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([{key:row[key] for key in ('lab','idea','eligible_distinct_seeds','mean_effect','status','excluded')} for row in result['ideas']],indent=2))

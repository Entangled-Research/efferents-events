"""Runnable event contracts: real measured data, bounded compute, no fake verdicts."""
import importlib.util
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest
import yaml

from efferents.cluster.tracks import load_tracks

ROOT=Path(__file__).resolve().parents[1]/'deploy/events/oct24/tracks'


def module_for(track):
    spec=importlib.util.spec_from_file_location(track,ROOT/track/'submission/src/experiment.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogue_contains_three_labs_and_seven_scoped_ideas():
    tracks=load_tracks(ROOT)
    assert set(tracks)=={'quantum-measurement','gfp-fitness','vision-sampling'}
    assert sum(len(t.lab_yaml['students']) for t in tracks.values())==7
    for track in tracks.values():
        for idea in track.lab_yaml['students']:
            assert (track.submission/'ideas'/idea['id']/'hypothesis.md').is_file()
            assert (track.submission/'configs'/f"{idea['id']}.yaml").is_file()


@pytest.mark.parametrize('track,task',[
    ('quantum-measurement','correlations'),('quantum-measurement','readout'),
    ('gfp-fitness','prediction'),('gfp-fitness','distance'),
    ('vision-sampling','few_steps'),('vision-sampling','schedule'),('vision-sampling','reasoning')])
def test_every_idea_measures_finite_results_and_produces_a_gallery(track,task):
    config=yaml.safe_load((ROOT/track/'submission/configs'/f'{task}.yaml').read_text())
    metrics,fig=module_for(track).run(config,smoke=True)
    try:
        assert metrics['coverage']==1
        assert all(np.isfinite(v) for v in metrics.values())
        assert len(fig.axes)>0
        if task=='few_steps':
            assert metrics['denoiser_calls']*4==metrics['baseline_calls']
        if task=='schedule':
            assert metrics['denoiser_calls']==metrics['baseline_calls']
        if task in ('prediction','distance'):
            assert metrics['n_train']>=200 and metrics['n_test']>=200
    finally:
        plt.close(fig)


def test_quantum_reference_is_a_normalized_distribution_and_fits_have_no_oracle_argument():
    module=module_for('quantum-measurement')
    states,p=module.target(6,.7)
    assert np.isclose(p.sum(),1) and np.all(p>=0)
    samples=states[np.random.default_rng(1).choice(len(p),256,p=p)]
    for structured in (True,False):
        q=module.fit(samples,states,structured)
        assert np.isclose(q.sum(),1) and np.all(q>=0)


def test_templates_materialize_as_valid_participant_labs(tmp_path):
    import shutil
    from efferents.lab import LabConfig
    for track in load_tracks(ROOT).values():
        destination=tmp_path/track.id
        shutil.copytree(track.submission,destination)
        shutil.copy2(destination/'starter-hypothesis.md',destination/'hypothesis.md')
        raw=yaml.safe_load((destination/'lab.yaml').read_text())
        raw['falsifiers']=list(track.example_falsifiers)
        (destination/'lab.yaml').write_text(yaml.safe_dump(raw))
        cfg=LabConfig.from_submission(destination)
        assert len(cfg.students)==len(track.lab_yaml['students'])

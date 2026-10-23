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
    ('quantum-measurement','encoding'),('quantum-measurement','tensor_network'),
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


def test_quantum_encodings_match_explicit_small_state_overlaps():
    module=module_for('quantum-measurement')
    x=np.array([[0.2,0.7],[0.8,0.1]])
    states=[]
    for row in x:
        local=[np.array([np.cos(np.pi*.25*v/2),np.sin(np.pi*.25*v/2)]) for v in row]
        states.append(np.kron(*local))
    expected=np.abs(np.array(states)@np.array(states).T)**2
    assert np.allclose(module.rotation_kernel(x,x,.25),expected)
    amplitudes=module.normalize(x)
    kernel=module.fidelity_kernel(amplitudes,amplitudes)
    assert np.allclose(np.diag(kernel),1)
    assert np.linalg.eigvalsh(kernel).min()>=-1e-10


@pytest.mark.parametrize('ordering',['row_major','interleaved'])
def test_complex_tensor_train_preserves_phase_at_full_rank_and_counts_storage(ordering):
    module=module_for('quantum-measurement')
    rng=np.random.default_rng(12)
    vector=rng.normal(size=64)+1j*rng.normal(size=64)
    exact,count=module.tt_compress(vector,8,ordering)
    assert np.allclose(exact,vector) and count>64
    low,low_count=module.tt_compress(vector,2,ordering)
    assert low_count==40 and np.linalg.norm(low-vector)>0
    # A separable complex state is exactly representable at bond one.
    product=np.array([1.0+0j])
    for _ in range(6):
        product=np.kron(product,rng.normal(size=2)+1j*rng.normal(size=2))
    restored,_=module.tt_compress(product,1,ordering)
    assert np.allclose(restored,product)


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

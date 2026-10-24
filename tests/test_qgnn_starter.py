"""Verify real circuit behavior and the synthetic benchmark's declared limits."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from efferents.cluster.tracks import validate_track

ROOT = Path(__file__).resolve().parents[1] / 'deploy/events/oct24/tracks/quantum-gnn'


def experiment():
    spec = importlib.util.spec_from_file_location('qgnn_experiment', ROOT/'submission/src/experiment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qgnn_is_three_idea_quantum_journal_lab():
    from efferents.journals import journal_for_domain
    track = validate_track(ROOT)
    assert journal_for_domain(track.domain) == 'Physics & Dynamics'
    assert len(track.lab_yaml['students']) == 3
    assert track.lab_yaml['executor']['isolated_parallel_safe']
    assert {'coverage', 'evaluation_valid'} == {c['column'] for c in track.lab_yaml['metrics']['constraints']}


def test_circuit_is_unitary_and_permutation_invariant():
    ex = experiment()
    rng = np.random.default_rng(73)
    state = rng.normal(size=64) + 1j*rng.normal(size=64)
    state /= np.linalg.norm(state)
    assert np.linalg.norm(ex.ry(state, 3, .65)) == pytest.approx(1)
    graphs, _ = ex.graphs(0, 2)
    angles = rng.normal(size=(2,2))
    for graph in graphs:
        permutation = rng.permutation(6)
        np.testing.assert_allclose(ex.graph_features(graph, angles),
                                   ex.graph_features(graph[np.ix_(permutation,permutation)], angles), atol=1e-12)


@pytest.mark.parametrize('task', ['entanglement','encoding','depth'])
def test_full_protocol_and_smoke_eligibility(task):
    ex = experiment()
    config = {'task':task, 'seed':0, 'layers':2, 'candidates':2}
    full, smoke = ex.run(config), ex.run(config, smoke=True)
    assert full['evaluation_valid'] == 1 and smoke['evaluation_valid'] == 0
    assert full['classical_triangle_accuracy'] == 1
    assert full['effect'] == pytest.approx(full['baseline_error'] - full['treatment_error'] - .05)
    assert full['provenance']['independent_topologies'] == 2
    assert len(full['samples']) == full['provenance']['test_permutations']
    assert not any((ROOT/'submission'/'lab').glob('runs*'))

"""Six-qubit graph circuit classifier. Synthetic topology benchmark, no advantage claim."""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

import numpy as np
import yaml


def ry(state, qubit, theta):
    out = state.copy()
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    for index in range(len(state)):
        if not (index >> qubit) & 1:
            other = index | (1 << qubit)
            out[index] = c * state[index] - s * state[other]
            out[other] = s * state[index] + c * state[other]
    return out


def graph_features(adjacency, angles, *, entangle=True, encoding='degree'):
    """Shared trainable RY gates and edge-conditioned RZZ quantum messages.

    Pool observables symmetrically; node permutations do not change features.
    Exact statevectors, no shots, noise, hardware or speedup accounting.
    """
    n = len(adjacency)
    indices = np.arange(2 ** n)
    z = np.array([1 - 2 * ((indices >> q) & 1) for q in range(n)])
    state = np.zeros(2 ** n, dtype=complex)
    state[0] = 1
    degree = adjacency.sum(axis=1) / (n - 1)
    encoded = degree if encoding == 'degree' else np.ones(n) * .5
    edges = [(i, j) for i in range(n) for j in range(i) if adjacency[i, j]]
    for layer, (rotation, message) in enumerate(angles):
        for q in range(n):
            state = ry(state, q, rotation + np.pi * encoded[q])
        if entangle:
            for i, j in edges:
                state *= np.exp(-.5j * message * z[i] * z[j])
    probability = abs(state) ** 2
    local = z @ probability
    edge = np.array([(z[i] * z[j]) @ probability for i, j in edges])
    return np.array([local.mean(), (local ** 2).mean(),
                     edge.mean() if len(edge) else 0, np.prod(z, axis=0) @ probability])


def graphs(seed, per_class):
    """Two known six-node, degree-2 families: a cycle vs disjoint triangles.

    Permutations are augmentation, not independent graph instances. This is a
    controlled expressivity check; no generalisation beyond these two topologies.
    """
    rng = np.random.default_rng(seed)
    data, labels = [], []
    for label in (0, 1):
        base = np.zeros((6, 6))
        edges = [(i, (i + 1) % 6) for i in range(6)] if label == 0 else [(0,1),(1,2),(2,0),(3,4),(4,5),(5,3)]
        for i, j in edges:
            base[i, j] = base[j, i] = 1
        for _ in range(per_class):
            p = rng.permutation(6)
            data.append(base[np.ix_(p, p)])
            labels.append(label)
    order = rng.permutation(len(data))
    return [data[i] for i in order], np.array(labels)[order]


def fit_predict(train, y, test, ridge=.1):
    center = train.mean(axis=0)
    scale = train.std(axis=0)
    scale[scale < 1e-8] = 1
    x = np.column_stack([np.ones(len(train)), (train - center) / scale])
    xx = np.column_stack([np.ones(len(test)), (test - center) / scale])
    weights = np.linalg.solve(x.T @ x + ridge * np.eye(x.shape[1]), x.T @ y)
    return (xx @ weights >= .5).astype(int)


def run(config, smoke=False):
    started = time.monotonic()
    seed = int(config.get('seed', 0))
    task = config.get('task', 'entanglement')
    if task not in {'entanglement', 'encoding', 'depth'}:
        raise ValueError('unknown QGNN task')
    layers = int(config.get('layers', 2))
    candidates = int(config.get('candidates', 8))
    if not 1 <= layers <= 4 or not 1 <= candidates <= 32:
        raise ValueError('bounded simulation requires layers 1..4, candidates 1..32')
    if smoke:
        candidates = 1
    rng = np.random.default_rng(seed)
    train, ytrain = graphs(seed * 3, 4)
    validation, yval = graphs(seed * 3 + 1, 2)
    test, ytest = graphs(seed * 3 + 2, 4)
    # Validation chooses circuit parameters; test labels are never used in selection.
    def search(entangle, encoding, depth):
        best = None
        for _ in range(candidates):
            angles = rng.uniform(-np.pi, np.pi, size=(depth, 2))
            xtrain = np.array([graph_features(g, angles, entangle=entangle, encoding=encoding) for g in train])
            xval = np.array([graph_features(g, angles, entangle=entangle, encoding=encoding) for g in validation])
            score = float((fit_predict(xtrain, ytrain, xval) == yval).mean())
            if best is None or score > best[0]:
                best = (score, angles, xtrain)
        x = np.array([graph_features(g, best[1], entangle=entangle, encoding=encoding) for g in test])
        predictions = fit_predict(best[2], ytrain, x)
        return float((predictions == ytest).mean()), predictions
    # Equal parameter-search budget per arm; depth changes parameters explicitly.
    baseline_args = (False, 'degree', layers) if task == 'entanglement' else ((True, 'constant', layers) if task == 'encoding' else (True, 'degree', 1))
    baseline, _ = search(*baseline_args)
    treatment, predictions = search(True, 'degree', layers)
    classical_train = np.array([[np.trace(g @ g @ g) / 6] for g in train])
    classical_test = np.array([[np.trace(g @ g @ g) / 6] for g in test])
    spectral = float((fit_predict(classical_train, ytrain, classical_test) == ytest).mean())
    identity = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]
    return {'effect': treatment - baseline - .05, 'baseline_error': 1 - baseline,
            'treatment_error': 1 - treatment, 'quantum_accuracy': treatment,
            'classical_triangle_accuracy': spectral, 'coverage': 1,
            'evaluation_valid': int(not smoke), 'qubits': 6,
            'parameters': layers * 2, 'candidates_per_arm': candidates,
            'wall_time_s': time.monotonic() - started,
            'provenance': {'seed': seed, 'task': task, 'config_sha256': identity,
                           'dataset': 'synthetic cycle6 versus two disjoint triangles',
                           'independent_topologies': 2, 'test_permutations': len(test),
                           'limitations': 'Same two isomorphism classes across splits; expressivity only, no population generalization or quantum advantage.'},
            'samples': [{'true_label': int(y), 'prediction': int(p)} for y, p in zip(ytest, predictions)],
            'artifacts': []}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--smoke', action='store_true')
    options = parser.parse_args()
    config_path = Path(options.config)
    result = run(yaml.safe_load(config_path.read_text()), options.smoke)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder = Path(__file__).resolve().parents[1] / 'artifacts'
    folder.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    path = folder / f'{identifier}.png'
    figure, axes = plt.subplots(1, 2, figsize=(8, 3))
    axes[0].bar(['ablation', 'QGNN', 'classical'],
                [1-result['baseline_error'], result['quantum_accuracy'], result['classical_triangle_accuracy']])
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title('Two-topology expressivity check')
    axes[1].axis('off')
    axes[1].table(cellText=[[i, s['true_label'], s['prediction']] for i,s in enumerate(result['samples'])],
                  colLabels=['permutation', 'truth', 'prediction'], loc='center')
    figure.suptitle(f"seed {result['provenance']['seed']} · permutations are not new topologies")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)
    metrics = {k:v for k,v in result.items() if isinstance(v, (int, float))}
    print(json.dumps({'run_id': identifier, 'metrics': metrics,
                      'artifacts': [{'kind':'samples', 'path':str(path)}],
                      'elapsed_s': result['wall_time_s'],
                      'provenance': {**result['provenance'],
                        'executor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest()}}))

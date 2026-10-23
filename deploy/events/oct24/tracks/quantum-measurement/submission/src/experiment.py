"""CPU experiments on finite-shot quantum measurement, never hardware advantage."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml


def target(n, field):
    states = ((np.arange(2**n)[:, None] >> np.arange(n)) & 1).astype(int)
    z = 1 - 2 * states
    h = np.diag(-np.sum(z * np.roll(z, 1, axis=1), axis=1).astype(float))
    for i in range(n):
        h[np.arange(2**n), np.arange(2**n) ^ (1 << i)] -= field
    _, vectors = np.linalg.eigh(h)
    p = vectors[:, 0] ** 2
    return states, p / p.sum()


def fit(samples, states, structured):
    q = np.ones(len(states))
    if not structured:
        rates = (samples.sum(axis=0) + 0.5) / (len(samples) + 1)
        return np.prod(np.where(states, rates, 1 - rates), axis=1)
    rate = (samples[:, 0].sum() + 0.5) / (len(samples) + 1)
    q *= np.where(states[:, 0], rate, 1 - rate)
    for i in range(1, states.shape[1]):
        for previous in (0, 1):
            group = samples[samples[:, i - 1] == previous, i]
            rate = (group.sum() + 0.5) / (len(group) + 1)
            mask = states[:, i - 1] == previous
            q[mask] *= np.where(states[mask, i], rate, 1 - rate)
    return q / q.sum()


def run(config, smoke=False):
    rng = np.random.default_rng(int(config.get("seed", 0)))
    n, shots = int(config.get("qubits", 6)), int(config.get("shots", 512))
    if not 2 <= n <= 8 or not 128 <= shots <= 100000:
        raise ValueError("Use 2–8 qubits and 128–100000 total shots")
    states, p = target(n, float(config.get("field", 0.7)))
    task = config.get("task", "correlations")
    if task == "correlations":
        sample = states[rng.choice(len(p), shots, p=p)]
        baseline, treatment = fit(sample, states, False), fit(sample, states, True)
    elif task == "readout":
        flip01, flip10 = (
            float(config.get("flip01", 0.04)),
            float(config.get("flip10", 0.10)),
        )
        fraction = float(config.get("calibration_fraction", 0.3))
        calibration = max(2 * n, int(shots * fraction) // (2 * n) * (2 * n))
        if calibration >= shots:
            raise ValueError("Calibration must leave signal shots")
        per_state = calibration // (2 * n)
        estimate01 = rng.binomial(per_state, flip01, n) / per_state
        estimate10 = rng.binomial(per_state, flip10, n) / per_state
        if np.any(estimate01 + estimate10 >= 0.95):
            raise ValueError("Calibration too noisy to invert; increase shots")

        def observed(count):
            bits = states[rng.choice(len(p), count, p=p)].copy()
            flips = rng.random(bits.shape) < np.where(bits, flip10, flip01)
            bits ^= flips.astype(int)
            return np.bincount(bits @ (1 << np.arange(n)), minlength=len(p)) / count

        # Calibration is charged to the treatment's SAME total shot budget.
        baseline, measured = observed(shots), observed(shots - calibration)
        matrix = np.ones((len(states), len(states)))
        for i in range(n):
            matrix *= np.where(
                states[None, :, i] == 0,
                np.where(states[:, None, i] == 0, 1 - estimate01[i], estimate01[i]),
                np.where(states[:, None, i] == 0, estimate10[i], 1 - estimate10[i]),
            )
        treatment = np.maximum(np.linalg.solve(matrix, measured), 0)
        treatment /= treatment.sum()
    else:
        raise ValueError("Unknown task")
    baseline_error = float(np.abs(p - baseline).sum() / 2)
    treatment_error = float(np.abs(p - treatment).sum() / 2)
    effect = (baseline_error - treatment_error) / max(baseline_error, 1e-12) - 0.10
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.plot(p, label="exact reference", color="#2d5379")
    ax.plot(baseline, label="baseline", alpha=0.7)
    ax.plot(treatment, label="treatment", alpha=0.7)
    ax.set(
        xlabel="computational-basis outcome",
        ylabel="probability",
        title=f"{task}: {shots} total shots",
    )
    ax.legend()
    fig.tight_layout()
    return {
        "effect": effect,
        "baseline_error": baseline_error,
        "treatment_error": treatment_error,
        "shots": shots,
        "qubits": n,
        "coverage": 1,
    }, fig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text())
    started = time.perf_counter()
    metrics, fig = run(config, args.smoke)
    folder = Path(__file__).resolve().parents[1] / "artifacts"
    folder.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    path = folder / f"{identifier}.png"
    fig.savefig(path)
    plt.close(fig)
    print(
        json.dumps(
            {
                "run_id": identifier,
                "metrics": metrics,
                "artifacts": [{"kind": "samples", "path": str(path)}],
                "elapsed_s": time.perf_counter() - started,
                "provenance": {
                    "config_sha256": hashlib.sha256(
                        config_path.read_bytes()
                    ).hexdigest(),
                    "task": config.get("task"),
                    "seed": config.get("seed"),
                },
            }
        )
    )


if __name__ == "__main__":
    main()

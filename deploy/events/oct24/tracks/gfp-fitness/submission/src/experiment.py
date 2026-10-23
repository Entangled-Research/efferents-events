"""Measured GFP fluorescence: prediction and mutational-distance generalization."""

import argparse
import csv
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


def features(mutants, dimensions=256):
    x = np.zeros((len(mutants), dimensions + 1))
    x[:, 0] = 1
    for i, mutant in enumerate(mutants):
        for mutation in mutant.split(":"):
            digest = hashlib.blake2b(mutation.encode(), digest_size=4).digest()
            index = int.from_bytes(digest, "little")
            x[i, 1 + index % dimensions] += 1 if index & 256 else -1
    return x


def fit_predict(x, y, train, test, ridge):
    matrix = x[train].T @ x[train] + ridge * np.eye(x.shape[1])
    matrix[0, 0] -= ridge  # unpenalized intercept
    coef = np.linalg.solve(matrix, x[train].T @ y[train])
    return x[test] @ coef


def run(config, smoke=False):
    rng = np.random.default_rng(int(config.get("seed", 0)))
    path = Path(__file__).resolve().parents[1] / "data/GFP_AEQVI_Sarkisyan_2016.csv"
    expected = json.loads((path.parent / "provenance.json").read_text())["sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Dataset checksum differs from pinned source")
    rows = list(csv.DictReader(path.open()))
    # A fixed content-based subset is independent of labels and run seed.
    rows.sort(key=lambda r: hashlib.sha256(r["mutant"].encode()).hexdigest())
    rows = rows[: min(int(config.get("max_rows", 6000)), 3000 if smoke else 20000)]
    mutants = [r["mutant"] for r in rows]
    y = np.array([float(r["DMS_score"]) for r in rows])
    count = np.array([len(m.split(":")) for m in mutants])
    x = features(mutants)
    order = rng.permutation(len(y))
    train, test = order[: int(0.7 * len(y))], order[int(0.7 * len(y)) :]
    ridge = float(config.get("ridge", 10))
    if ridge <= 0:
        raise ValueError("ridge must be positive")
    prediction = fit_predict(x, y, train, test, ridge)
    means = {k: y[train][count[train] == k].mean() for k in np.unique(count[train])}
    baseline = np.array([means.get(k, y[train].mean()) for k in count[test]])
    baseline_error = float(np.sqrt(np.mean((baseline - y[test]) ** 2)))
    treatment_error = float(np.sqrt(np.mean((prediction - y[test]) ** 2)))
    comparison_indices = test.copy()
    comparison_prediction = baseline.copy()
    task = config.get("task", "prediction")
    if task == "prediction":
        effect = (baseline_error - treatment_error) / baseline_error - 0.10
        title = "Held-out fluorescence: count baseline vs mutation features"
    elif task == "distance":
        near = np.flatnonzero(count <= 2)
        far = np.flatnonzero(count >= 3)
        rng.shuffle(near)
        rng.shuffle(far)
        size = min(len(train), len(near))
        ntest = min(len(test), len(far))
        if size < 200 or ntest < 200:
            raise ValueError("Insufficient mutation-distance coverage")
        # Match training/test sizes between protocols. Neither sees held-out labels.
        random_prediction = fit_predict(x, y, train[:size], test[:ntest], ridge)
        baseline_error = float(
            np.sqrt(np.mean((random_prediction - y[test[:ntest]]) ** 2))
        )
        comparison_indices = test[:ntest].copy()
        comparison_prediction = random_prediction.copy()
        prediction = fit_predict(x, y, near[:size], far[:ntest], ridge)
        test = far[:ntest]
        treatment_error = float(np.sqrt(np.mean((prediction - y[test]) ** 2)))
        effect = (treatment_error - baseline_error) / baseline_error - 0.10
        title = "Distance holdout (≥3 mutations), trained on ≤2 mutations"
    else:
        raise ValueError("Unknown task")
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.scatter(y[test], prediction, s=5, alpha=0.25)
    ax.plot([y.min(), y.max()], [y.min(), y.max()], color="#a8502b")
    ax.set(
        xlabel="measured log fluorescence",
        ylabel="predicted log fluorescence",
        title=title,
    )
    fig.tight_layout()
    metrics = {
        "effect": effect,
        "baseline_error": baseline_error,
        "treatment_error": treatment_error,
        "n_train": len(train) if task == "prediction" else size,
        "n_test": len(test),
        "coverage": 1,
    }
    # Preserve the requested mutation-distance diagnostics without changing any
    # fit, split or headline. Empty strata report n=0 and omit unmeasured RMSE.
    for mutations in sorted(set(count.tolist())):
        for arm, indices, values in (("baseline", comparison_indices, comparison_prediction),
                                      ("treatment", test, prediction)):
            mask = count[indices] == mutations
            prefix = f"{arm}_mutations_{mutations}"
            metrics[prefix + "_n"] = int(mask.sum())
            if mask.any():
                metrics[prefix + "_rmse"] = float(np.sqrt(np.mean((values[mask]-y[indices][mask])**2)))
    return metrics, fig


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
                    "dataset_sha256": json.loads(
                        (
                            Path(__file__).resolve().parents[1] / "data/provenance.json"
                        ).read_text()
                    )["sha256"],
                    "task": config.get("task"),
                    "seed": config.get("seed"),
                },
            }
        )
    )


if __name__ == "__main__":
    main()

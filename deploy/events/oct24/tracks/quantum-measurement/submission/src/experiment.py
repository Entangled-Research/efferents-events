"""Exact feature-map kernels and complex TT-SVD on real digit images, CPU only."""
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


def load_digits():
    folder = Path(__file__).resolve().parents[1] / "dataset"
    path = folder / "optdigits.tes"
    expected = json.loads((folder / "provenance.json").read_text())["sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Digit dataset checksum mismatch")
    rows = np.loadtxt(path, delimiter=",")
    return rows[:, :64] / 16, rows[:, 64].astype(int)


def split_data(x, y, rng, n_train, n_test):
    train, test = [], []
    for label in range(10):
        indices = rng.permutation(np.flatnonzero(y == label))
        if n_train + n_test > len(indices):
            raise ValueError("Not enough examples for disjoint stratified splits")
        train.extend(indices[:n_train])
        test.extend(indices[n_train:n_train + n_test])
    return x[train], y[train], x[test], y[test]


def normalize(x):
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError("Zero vectors cannot be amplitude encoded")
    return x / norms


def fidelity_kernel(x, z):
    return np.clip(np.abs(x.conj() @ z.T) ** 2, 0, 1)


def rotation_kernel(x, z, scale):
    # |<RY(pi*s*x)|RY(pi*s*z)>|^2 factors across 64 separable qubits.
    return np.prod(np.cos(np.pi * scale * (x[:, None, :] - z[None, :, :]) / 2) ** 2, axis=-1)


def predict(train_kernel, test_kernel, labels, ridge):
    weights = np.linalg.solve(train_kernel + ridge * np.eye(len(labels)), np.eye(10)[labels])
    return np.argmax(test_kernel @ weights, axis=1)


def tt_compress(vector, bond, ordering="row_major"):
    """Complex TT-SVD followed by exact contraction, returning actual core storage."""
    if bond not in (1, 2, 4, 8):
        raise ValueError("Use bond dimension 1, 2, 4 or 8")
    if ordering not in ("row_major", "interleaved"):
        raise ValueError("Unknown tensor index ordering")
    axes = (0, 1, 2, 3, 4, 5) if ordering == "row_major" else (0, 3, 1, 4, 2, 5)
    remaining = np.asarray(vector, dtype=complex).reshape((2,) * 6).transpose(axes)
    cores, rank = [], 1
    for _ in range(5):
        matrix = remaining.reshape(rank * 2, -1)
        u, s, vh = np.linalg.svd(matrix, full_matrices=False)
        keep = min(bond, len(s))
        cores.append(u[:, :keep].reshape(rank, 2, keep))
        remaining = s[:keep, None] * vh[:keep]
        rank = keep
    cores.append(remaining.reshape(rank, 2, 1))
    restored = cores[0]
    for core in cores[1:]:
        restored = np.tensordot(restored, core, axes=(-1, 0))
    restored = restored.reshape((2,) * 6).transpose(np.argsort(axes)).reshape(64)
    return restored, sum(core.size for core in cores)


def run(config, smoke=False):
    rng = np.random.default_rng(int(config.get("seed", 0)))
    n_train, n_test = int(config.get("train_per_class", 20)), int(config.get("test_per_class", 10))
    ridge, scale = float(config.get("ridge", 0.1)), float(config.get("angle_scale", 0.25))
    if not 2 <= n_train <= 80 or not 2 <= n_test <= 50 or not 0 < ridge <= 100 or not 0 < scale <= 2:
        raise ValueError("Use 2–80 train/class, 2–50 test/class, positive ridge<=100 and 0<angle_scale<=2")
    x, y = load_digits()
    train, labels, test, truth = split_data(x, y, rng, n_train, n_test)
    task = config.get("task", "encoding")
    metrics = {"n_train": len(train), "n_test": len(test), "coverage": 1}
    if task == "encoding":
        a, b = normalize(train), normalize(test)
        amplitude_train = fidelity_kernel(a, a)
        amplitude_test = fidelity_kernel(b, a)
        rotation_train = rotation_kernel(train, train, scale)
        rotation_test = rotation_kernel(test, train, scale)
        baseline_pred = predict(rotation_train, rotation_test, labels, ridge)
        treatment_pred = predict(amplitude_train, amplitude_test, labels, ridge)
        baseline_accuracy = float(np.mean(baseline_pred == truth))
        treatment_accuracy = float(np.mean(treatment_pred == truth))
        effect = treatment_accuracy - baseline_accuracy - 0.05
        off_diagonal = ~np.eye(len(train), dtype=bool)
        metrics.update(amplitude_qubits=6, rotation_qubits=64,
                       amplitude_kernel_mean=float(amplitude_train[off_diagonal].mean()),
                       rotation_kernel_mean=float(rotation_train[off_diagonal].mean()))
        fig, axes = plt.subplots(1, 3, figsize=(10, 3))
        axes[0].imshow(amplitude_train[:40, :40], vmin=0, vmax=1)
        axes[0].set_title("Amplitude fidelity")
        axes[1].imshow(rotation_train[:40, :40], vmin=0, vmax=1)
        axes[1].set_title("Rotation fidelity")
        axes[2].bar(["Rotation", "Amplitude"], [baseline_accuracy, treatment_accuracy], color=["#a8502b", "#2d5379"])
        axes[2].set(ylim=(0, 1), ylabel="Held-out accuracy")
        metrics.update(baseline_error=1-baseline_accuracy, treatment_error=1-treatment_accuracy)
    elif task == "tensor_network":
        bond, ordering = int(config.get("bond_dim", 2)), config.get("ordering", "row_major")
        a = normalize(np.fft.fft2(train.reshape(-1, 8, 8), norm="ortho").reshape(-1, 64))
        b = normalize(np.fft.fft2(test.reshape(-1, 8, 8), norm="ortho").reshape(-1, 64))
        compressed = [tt_compress(v, bond, ordering) for v in np.concatenate([a, b])]
        compressed_vectors = normalize(np.array([v for v, _ in compressed]))
        ca, cb = compressed_vectors[:len(a)], compressed_vectors[len(a):]
        dense_pred = predict(fidelity_kernel(a, a), fidelity_kernel(b, a), labels, ridge)
        compressed_pred = predict(fidelity_kernel(ca, ca), fidelity_kernel(cb, ca), labels, ridge)
        baseline_accuracy = float(np.mean(dense_pred == truth))
        treatment_accuracy = float(np.mean(compressed_pred == truth))
        fidelity = float(np.mean(np.abs(np.sum(b.conj() * cb, axis=1)) ** 2))
        storage = max(count for _, count in compressed)
        ratio = storage / 64
        effect = min(fidelity - 0.90, treatment_accuracy - baseline_accuracy + 0.05, 0.75 - ratio)
        metrics.update(mean_fidelity=fidelity, stored_complex_coefficients=storage, storage_ratio=ratio,
                       bond_dim=bond, baseline_error=0.0, treatment_error=1-fidelity)
        # Inverse FFT retains each input's norm; no fitted image alignment or test labels.
        reconstructed = np.fft.ifft2(cb[:4].reshape(-1, 8, 8), norm="ortho")
        reconstructed *= np.linalg.norm(test[:4], axis=1)[:, None, None]
        fig, axes = plt.subplots(2, 4, figsize=(9, 4))
        for i in range(4):
            axes[0, i].imshow(test[i].reshape(8, 8), cmap="gray", vmin=0, vmax=1)
            axes[1, i].imshow(reconstructed[i].real, cmap="gray", vmin=0, vmax=1)
            axes[0, i].set_title(f"Original digit {truth[i]}")
            axes[1, i].set_title(f"Bond {bond} reconstruction")
        for ax in axes.flat:
            ax.axis("off")
    else:
        raise ValueError("Unknown task")
    metrics.update(effect=float(effect), baseline_accuracy=baseline_accuracy, treatment_accuracy=treatment_accuracy)
    fig.tight_layout()
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
    print(json.dumps({"run_id": identifier, "metrics": metrics,
                      "artifacts": [{"kind": "samples", "path": str(path)}],
                      "elapsed_s": time.perf_counter()-started,
                      "provenance": {"config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                                     "task": config.get("task"), "seed": config.get("seed"),
                                     "dataset_sha256": json.loads((Path(__file__).resolve().parents[1]/"dataset/provenance.json").read_text())["sha256"]}}))


if __name__ == "__main__":
    main()

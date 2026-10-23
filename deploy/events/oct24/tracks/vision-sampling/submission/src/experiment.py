"""Tiny image diffusion with a fixed analytic denoiser; CPU spatial reasoning."""

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


def templates():
    yy, xx = np.mgrid[:16, :16]
    images = []
    for shape in ("circle", "square"):
        for cx in (4, 8, 12):
            for cy in (4, 8, 12):
                mask = (
                    ((xx - cx) ** 2 + (yy - cy) ** 2 <= 9)
                    if shape == "circle"
                    else ((abs(xx - cx) <= 2) & (abs(yy - cy) <= 2))
                )
                images.append(mask.astype(float) * 2 - 1)
    return np.array(images)


def sample(bank, noise, steps, schedule):
    # Exact posterior-mean denoiser for an equally weighted finite clean-image
    # mixture. No training, hidden pretrained checkpoint or GPU is required.
    t = np.linspace(1, 0, steps + 1)
    if schedule == "late":
        t = t**2  # More evaluations near clean time t=0.
    elif schedule != "uniform":
        raise ValueError("schedule must be uniform or late")
    alpha = 1 / (1 + np.exp(12 * (2 * t - 1)))
    x = noise.copy()
    flat = bank.reshape(len(bank), -1)
    for a, b in zip(alpha[:-1], alpha[1:]):
        distance = ((x[:, None, :] - np.sqrt(a) * flat[None, :, :]) ** 2).sum(axis=2)
        logits = -distance / (2 * (1 - a))
        logits -= logits.max(axis=1, keepdims=True)
        weights = np.exp(logits)
        weights /= weights.sum(axis=1, keepdims=True)
        clean = weights @ flat
        epsilon = (x - np.sqrt(a) * clean) / np.sqrt(1 - a)
        x = np.sqrt(b) * clean + np.sqrt(1 - b) * epsilon
    distance = ((x[:, None, :] - flat[None, :, :]) ** 2).mean(axis=2)
    nearest = distance.argmin(axis=1)
    error = distance.min(axis=1)
    histogram = np.bincount(nearest, minlength=len(bank)) / len(x)
    return (
        x.reshape(-1, 16, 16),
        float((error < 0.05).mean()),
        float(error.mean()),
        float(np.abs(histogram - 1 / len(bank)).sum() / 2),
    )


def scenes(rng, count, shifted=False):
    # Red and blue rectangles. Model input is pixels, never the generator's
    # object coordinates. The graph branch extracts centroids from color masks.
    images = np.zeros((count, 16, 16, 3))
    labels = []
    for i in range(count):
        if shifted:
            x1, x2 = rng.choice(np.arange(2, 14), 2, replace=False)
        else:
            x1, x2 = rng.choice(np.arange(4, 12), 2, replace=False)
        y1, y2 = rng.integers(2, 14, 2)
        images[i, y1 - 1 : y1 + 2, x1 - 1 : x1 + 2, 0] = 1
        images[i, y2 - 1 : y2 + 2, x2 - 1 : x2 + 2, 2] = 1
        labels.append(int(x1 < x2))
    return images, np.array(labels)


def reasoning(rng, count):
    train, y = scenes(rng, 600)
    test, truth = scenes(rng, count, shifted=True)

    # Direct ridge predictor on flattened pixels, contrasted with an explicit
    # intermediate scene graph. This tests a local algorithmic pipeline, not a VLM.
    def down(x):
        values = x.reshape(len(x), 8, 2, 8, 2, 3).mean(axis=(2, 4)).reshape(len(x), -1)
        return np.column_stack([np.ones(len(x)), values])

    x = down(train)
    z = down(test)
    coef = np.linalg.solve(x.T @ x + 2 * np.eye(x.shape[1]), x.T @ (2 * y - 1))
    direct = z @ coef > 0
    xx = np.arange(16)[None, None, :]
    red = test[:, :, :, 0]
    blue = test[:, :, :, 2]
    red_x = (red * xx).sum(axis=(1, 2)) / red.sum(axis=(1, 2))
    blue_x = (blue * xx).sum(axis=(1, 2)) / blue.sum(axis=(1, 2))
    graph = red_x < blue_x
    return test, float((direct == truth).mean()), float((graph == truth).mean())


def run(config, smoke=False):
    rng = np.random.default_rng(int(config.get("seed", 0)))
    count = 64 if smoke else int(config.get("samples", 256))
    if not 32 <= count <= 2048:
        raise ValueError("Use 32–2048 samples")
    task = config.get("task", "few_steps")
    if task == "reasoning":
        images, baseline, treatment = reasoning(rng, count)
        effect = treatment - baseline - 0.05
        metrics = {
            "effect": effect,
            "baseline_error": 1 - baseline,
            "treatment_error": 1 - treatment,
            "baseline_accuracy": baseline,
            "treatment_accuracy": treatment,
            "coverage": 1,
            "samples": count,
        }
    else:
        bank = templates()
        noise = rng.normal(size=(count, 256))
        steps = int(config.get("steps", 8))
        reference = int(config.get("reference_steps", 32))
        if not 2 <= steps <= 64 or not 2 <= reference <= 64:
            raise ValueError("Use 2–64 denoiser evaluations")
        if task == "few_steps":
            _, base_valid, base_error, base_tv = sample(
                bank, noise, reference, "uniform"
            )
            images, valid, error, tv = sample(bank, noise, steps, "uniform")
            # Non-inferiority margin: effect >=0 when within five points.
            effect = min(valid - base_valid + 0.05, base_tv - tv + 0.05)
        elif task == "schedule":
            _, base_valid, base_error, base_tv = sample(bank, noise, steps, "uniform")
            images, valid, error, tv = sample(bank, noise, steps, "late")
            effect = base_tv - tv - 0.02
        else:
            raise ValueError("Unknown task")
        metrics = {
            "effect": effect,
            "baseline_error": base_error,
            "treatment_error": error,
            "baseline_validity": base_valid,
            "treatment_validity": valid,
            "baseline_mode_tv": base_tv,
            "treatment_mode_tv": tv,
            "denoiser_calls": steps,
            "baseline_calls": reference if task == "few_steps" else steps,
            "coverage": 1,
            "samples": count,
        }
    fig, axes = plt.subplots(2, 8, figsize=(10, 3))
    for ax, image in zip(axes.flat, images[:16]):
        ax.imshow(
            np.clip(image, 0, 1) if task == "reasoning" else image,
            cmap="gray",
            vmin=-1,
            vmax=1,
        )
        ax.axis("off")
    fig.suptitle(f"{task} · seed {config.get('seed', 0)} · synthetic 16×16 images")
    fig.tight_layout()
    return metrics, fig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    path = Path(args.config)
    config = yaml.safe_load(path.read_text())
    started = time.perf_counter()
    metrics, fig = run(config, args.smoke)
    folder = Path(__file__).resolve().parents[1] / "artifacts"
    folder.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    output = folder / f"{identifier}.png"
    fig.savefig(output)
    plt.close(fig)
    print(
        json.dumps(
            {
                "run_id": identifier,
                "metrics": metrics,
                "artifacts": [{"kind": "samples", "path": str(output)}],
                "elapsed_s": time.perf_counter() - started,
                "provenance": {
                    "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "task": config.get("task"),
                    "seed": config.get("seed"),
                    "denoiser": "analytic finite image mixture; not a trained neural network",
                },
            }
        )
    )


if __name__ == "__main__":
    main()

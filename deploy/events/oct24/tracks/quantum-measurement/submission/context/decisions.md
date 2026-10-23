# Implemented executor inventory and initial research order

All tasks below are implemented, with runnable per-task configs and bounded CPU executors. A separate new implementation is not a prerequisite. Run the registered comparisons first; optional architecture proposals must not replace them. Inspect src/experiment.py if uncertain.

- encoding: use configs/encoding.yaml and config.task=encoding
- tensor_network: use configs/tensor_network.yaml and config.task=tensor_network

encoding: effect = amplitude accuracy - rotation accuracy - 0.05. tensor_network: effect = min(fidelity - 0.90, compressed accuracy - dense accuracy + 0.05, 0.75 - core-storage ratio). Bond dimensions 1/2/4/8 and row_major/interleaved are already implemented; max-rank reconstruction is unit-tested. Do not block the registered bond-2 experiment on a new exact_mps module.

The target has ALREADY been subtracted inside effect. effect >= 0 meets the numeric target for that run; do not subtract it again or demand effect >= 0.05/0.10. A numerical pass alone is not statistical or scientific acceptance.

Start with five distinct seeds 0–4 at each idea’s registered default settings, each attributed to that idea. Retrying an infrastructure-failed config is allowed because it yielded no measurement. Preserve failed runs. After the initial comparison, use separate campaigns for changed thresholds, data sizes, regularizers, schedules or tensor orderings. Record validity concerns instead of silently rewriting the target.

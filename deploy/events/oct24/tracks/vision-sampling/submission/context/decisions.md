# Implemented executor inventory and initial research order

All tasks below are implemented, with runnable per-task configs and bounded CPU executors. A separate new implementation is not a prerequisite. Run the registered comparisons first; optional architecture proposals must not replace them. Inspect src/experiment.py if uncertain.

- few_steps: use configs/few_steps.yaml and config.task=few_steps
- schedule: use configs/schedule.yaml and config.task=schedule
- reasoning: use configs/reasoning.yaml and config.task=reasoning

few_steps: effect = min(validity_8 - validity_32 + 0.05, TV_32 - TV_8 + 0.05). schedule: effect = TV_uniform - TV_quadratic - 0.02; the quadratic late-focused schedule is already implemented. reasoning: effect = graph accuracy - pixel accuracy - 0.05; both methods see pixels. Do not block the registered schedule comparison on a new schedule_policy module.

The target has ALREADY been subtracted inside effect. effect >= 0 meets the numeric target for that run; do not subtract it again or demand effect >= 0.05/0.10. A numerical pass alone is not statistical or scientific acceptance.

Start with five distinct seeds 0–4 at each idea’s registered default settings, each attributed to that idea. Retrying an infrastructure-failed config is allowed because it yielded no measurement. Preserve failed runs. After the initial comparison, use separate campaigns for changed thresholds, data sizes, regularizers, schedules or tensor orderings. Record validity concerns instead of silently rewriting the target.

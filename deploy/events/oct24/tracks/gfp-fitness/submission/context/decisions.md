# Implemented executor inventory and initial research order

All tasks below are implemented, with runnable per-task configs and bounded CPU executors. A separate new implementation is not a prerequisite. Run the registered comparisons first; optional architecture proposals must not replace them. Inspect src/experiment.py if uncertain.

- prediction: use configs/prediction.yaml and config.task=prediction
- distance: use configs/distance.yaml and config.task=distance

prediction: effect = (count-baseline RMSE - mutation-feature RMSE) / count-baseline RMSE - 0.10. distance: effect = (distance-shift RMSE - random-split RMSE) / random-split RMSE - 0.10. Both matched-size protocols and the task dispatch are already implemented in src/experiment.py. Do not block the registered comparison on a new distance_protocol module.

The target has ALREADY been subtracted inside effect. effect >= 0 meets the numeric target for that run; do not subtract it again or demand effect >= 0.05/0.10. A numerical pass alone is not statistical or scientific acceptance.

Start with five distinct seeds 0–4 at each idea’s registered default settings, each attributed to that idea. Retrying an infrastructure-failed config is allowed because it yielded no measurement. Preserve failed runs. After the initial comparison, use separate campaigns for changed thresholds, data sizes, regularizers, schedules or tensor orderings. Record validity concerns instead of silently rewriting the target.

## After the initial comparison

These are bounded benchmark comparisons. A missed target is useful evidence, not a reason to retune the threshold. For a fresh replication reporting the failure, explicitly declare new_campaign.finding_kind=negative_result; for a bounded reproduction of a positive comparison, use verification. Collect fresh distinct seeds under the new registered campaign and cite the initial measured comparator. Keep headline_metric=effect and direction=max unless the owner registers a different numeric metric. Batch up to three distinct seed proposals per turn when the fixed protocol calls for replication. Missing or nonexistent metrics cannot support a paper. Complete valid review is required; never force acceptance.

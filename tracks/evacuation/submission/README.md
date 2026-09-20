# Congestion-aware evacuation event track

This CPU-only lab compares the same seeded building and evacuee positions under
two routing policies: static shortest path and a policy that periodically
replans with occupied and reserved cells as added path cost. It uses synthetic
scenarios and makes no claim about real-world evacuation safety.

This track is a template, not a launched lab. The event intake asks each
participant for their own hypothesis, then maps the approved falsifier onto
the numeric columns this runner reports. A suggested question is whether the
candidate improves median evacuation time by at least 10% across 12 paired
seeds while preserving at least 95% completion. After intake, vary the
configuration values within the approved claim. The event disables autonomous
source edits; do not treat this simulator as safety guidance.

## Local check

```bash
python3 -m unittest discover -s tests -v
python3 src/run_experiment.py --config configs/default.yaml
```

After the participant approves a hypothesis and the hub creates their lab,
`efferents validate --submission .` and a bounded dry run are available.

The last JSON object printed by `run_experiment.py` is the framework result.
The SVG replay and JSON summary are written under `artifacts/`; an initialized
lab copies them into its per-run evidence directory.

## Research directions

- Tune how local occupancy changes route cost.
- Decide when an evacuee abandons its current route.
- Balance exits without prescribing one assignment rule.
- Test staggered departures.
- Add controlled route diversity.
- Model corridor capacity in the search cost.
- Test blocked exits or noisy occupancy observations.

The event intake sets `autonomy.coder_enabled: false`, so source edits require
an operator-approved change outside the live experiment loop.

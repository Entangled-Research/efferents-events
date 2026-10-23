---
slug: schedule
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Where should a small sampler spend its steps?

## Original framing

At the same eight evaluations, does concentrating steps near the clean image preserve more modes?

## Operational restatement

A quadratic late-focused eight-evaluation schedule reduces total-variation distance of the generated mode distribution from uniform by at least 0.02 versus an eight-evaluation uniform schedule.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Hold the clean-image bank, denoiser, initial noise, sample count and evaluation budget fixed. Compare schedules over seeds 0–4; report validity alongside diversity. A late-focused schedule might fail or help fidelity while hurting diversity.

## Auxiliary assumptions

The default diffusion experiment uses a fixed analytic posterior-mean denoiser over 18 synthetic shape images, not a pretrained neural diffusion model. It isolates sampler behavior. The spatial experiment compares local pixel and scene-graph algorithms, not general vision-language model reasoning. Transfer to pretrained models or VLMs is an optional follow-up requiring separate resources and validation.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://arxiv.org/abs/2010.02502

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

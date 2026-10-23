---
slug: few_steps
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Can we cut sampling to eight steps without breaking shapes?

## Original framing

Where is the quality-versus-compute tradeoff for diffusion sampling?

## Operational restatement

Eight DDIM-style denoiser evaluations retain shape validity within five percentage points AND mode total-variation error within 0.05 of a 32-evaluation reference, using the same denoiser and initial noise.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Fix 256 samples and paired initial noises per seed. Validity is nearest-template pixel MSE <0.05. Test seeds 0–4. Report validity, nearest-template error, mode total-variation and measured time; a quality pass alone does not establish diversity. Steps must remain exactly 8 versus 32 for this claim.

## Auxiliary assumptions

The default diffusion experiment uses a fixed analytic posterior-mean denoiser over 18 synthetic shape images, not a pretrained neural diffusion model. It isolates sampler behavior. The spatial experiment compares local pixel and scene-graph algorithms, not general vision-language model reasoning. Transfer to pretrained models or VLMs is an optional follow-up requiring separate resources and validation.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://arxiv.org/abs/2010.02502

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

---
slug: reasoning
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Do intermediate scene graphs help with left and right?

## Original framing

Is it better to extract objects and their positions before answering a spatial question?

## Operational restatement

An intermediate color-mask centroid scene graph improves left/right accuracy by at least five percentage points over a ridge predictor on downsampled pixels when test scenes use a wider translation range.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Both methods receive only rendered RGB pixels. Train the pixel predictor on 600 labeled scenes; evaluate both on the same 256 shifted scenes for seeds 0–4. Generator coordinates define labels but must never be passed to the predictor. Report accuracy and failure galleries. The graph encodes the relation explicitly, so this is a pipeline comparison, not a matched-capacity reasoning claim.

## Auxiliary assumptions

The default diffusion experiment uses a fixed analytic posterior-mean denoiser over 18 synthetic shape images, not a pretrained neural diffusion model. It isolates sampler behavior. The spatial experiment compares local pixel and scene-graph algorithms, not general vision-language model reasoning. Transfer to pretrained models or VLMs is an optional follow-up requiring separate resources and validation.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://arxiv.org/abs/2010.02502

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

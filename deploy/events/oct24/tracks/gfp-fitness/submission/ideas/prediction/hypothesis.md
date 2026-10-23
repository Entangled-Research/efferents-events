---
slug: prediction
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Do mutation identities matter more than mutation count?

## Original framing

How much do mutation identities add beyond the number of changes to the protein?

## Operational restatement

On a fixed content-selected 6000-variant subset, a ridge model with hashed mutation-identity features reduces held-out fluorescence RMSE by at least 10% relative to a mutation-count mean predictor.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Use 70/30 train/test splits for seeds 0–4. Fit feature weights and count-bin means on training labels only; fix ridge=10 before testing. Report errors by mutation count and show a predicted-versus-measured scatter. Hashing collisions are a known model limitation. Do not tune on test labels.

## Auxiliary assumptions

Predicts measured log fluorescence for variants of one GFP protein, not thermodynamic stability or arbitrary proteins. The published paper already studies epistasis; this is a bounded reproduction/method comparison, not a claim of discovering epistasis. Dark variants have an assay floor; no causal or wet-lab conclusions.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://www.nature.com/articles/nature17995

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

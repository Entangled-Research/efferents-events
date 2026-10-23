---
slug: distance
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Does a good random-split score survive farther mutations?

## Original framing

Can a predictor trained close to the original protein handle variants with more mutations?

## Operational restatement

At matched train/test sizes, the same additive mutation-feature predictor has at least 10% higher RMSE when trained on variants with ≤2 mutations and tested on ≥3 than under a random split.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Run the random and mutational-distance protocols with the same fixed data subset, model, regularization and matched sizes. Seeds 0–4 resample within each protocol. Report each distance stratum; this tests a distribution shift, not a pure causal effect of distance.

## Auxiliary assumptions

Predicts measured log fluorescence for variants of one GFP protein, not thermodynamic stability or arbitrary proteins. The published paper already studies epistasis; this is a bounded reproduction/method comparison, not a claim of discovering epistasis. Dark variants have an assay floor; no causal or wet-lab conclusions.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://www.nature.com/articles/nature17995

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

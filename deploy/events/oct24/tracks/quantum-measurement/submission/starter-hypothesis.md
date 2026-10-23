---
slug: correlations
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Do correlations help when measurements are scarce?

## Original framing

Can a simple correlated model reconstruct quantum measurement outcomes better than treating every qubit independently?

## Operational restatement

At 512 signal shots on the six-qubit Ising ground state with field 0.7, an adjacent-qubit conditional model reduces total-variation error by at least 10% versus independent Bernoulli fits on the same samples.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Compare the two fitted distributions against the exact 64-outcome reference. Repeat seeds 0–4, then vary shots (128, 512, 2048) and field (0.4, 0.7, 1.2). Do not train on reference probabilities.

## Auxiliary assumptions

A six-qubit transverse-field Ising simulation. Computational-basis probabilities do not establish entanglement or quantum advantage. The exact reference is for scoring only; fits must use finite-shot samples.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://quantum.cloud.ibm.com/docs/en/guides/error-mitigation-and-suppression-techniques

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

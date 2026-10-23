---
slug: readout
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Is correcting noisy measurements worth the calibration cost?

## Original framing

Does readout calibration reduce distribution error when its extra measurements count against the same budget?

## Operational restatement

At 512 total shots and asymmetric readout noise (0→1=0.04, 1→0=0.10), calibrated correction reduces total-variation error by at least 10% versus uncorrected sampling. The correction arm spends 30% of its total shots on calibration.

## Falsifier(s)

The claim is refuted in this bounded benchmark if mean `effect` (signed margin above the stated target) is negative across five eligible seeds. A confidence interval crossing zero is inconclusive, not acceptance. Missing/failed measurements are not zero results.

## Test design

Each arm gets 512 total shots. Estimate each qubit’s calibration errors using calibration shots, invert the estimated channel, project negative probabilities to zero and renormalize. Compare to the exact reference over seeds 0–4. Repeat at 128 and 2048 shots; report bias/variance and projection effects.

## Auxiliary assumptions

A six-qubit transverse-field Ising simulation. Computational-basis probabilities do not establish entanglement or quantum advantage. The exact reference is for scoring only; fits must use finite-shot samples.

## Distinctiveness

A simple matched baseline could explain the result. Keep model/data/compute fixed except the named intervention. These thresholds are provisional event preregistrations, not literature-derived effects.

## References

- https://quantum.cloud.ibm.com/docs/en/guides/error-mitigation-and-suppression-techniques

## Intake log

2026-10-23: Model-led event starter prepared for Masha. No scientific results claimed; no human probe interview required.

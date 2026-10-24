---
slug: qgnn-depth
created: 2026-10-24
status: active
falsifiability_gate: passed
literature_pass: none
---

# Does a deeper circuit help?

## Original framing

Develop the best bounded quantum graph neural network, testing multiple ideas automatically.

## Operational restatement

Compare depth 2 or 3 with depth 1, retaining the same validation search budget and explicitly reporting parameter counts. Set task=depth. The treatment improves accuracy by at least 0.05 over the matched ablation on cycle6 versus disjoint-triangle classification.

## Falsifier(s)

Mean effect < 0 over five eligible seeds refutes this bounded claim. Missing/incomplete evaluations remain undecided; seed runs are parameter-search replications, not independent graph-topology samples.

## Test design

Six-qubit exact statevectors, shared RY node gates and edge-conditioned RZZ messages. Validation-only random-search parameter training (8 candidates per arm), fixed ridge readout, seeds 0–4. Train/validation/test use permutations of the same two topologies. Report classical triangle-count accuracy, both arm accuracies, parameter counts and wall time. No unseen-topology generalisation, hardware speedup or quantum advantage claim. Smoke is explicitly ineligible evidence.

## Auxiliary assumptions

Synthetic graphs, exact readout probabilities, no finite-shot or hardware noise. Equal random-search budgets do not match circuit depth or parameter count. The triangle-count baseline can solve these graph families exactly.

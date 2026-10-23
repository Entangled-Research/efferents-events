---
slug: encoding
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# Does amplitude or rotation encoding preserve digit similarity better?

## Original framing

If the same image becomes amplitudes or rotation angles, which representation keeps useful similarities for recognizing digits?

## Operational restatement

On 200 training and 100 held-out digit images, a squared-fidelity kernel from amplitude encoding improves classification accuracy by at least five percentage points over a product RY-rotation kernel at angle_scale=0.25, using the same ridge classifier.

## Falsifier(s)

Mean `effect` below zero over five eligible seeds refutes this bounded claim. A confidence interval crossing zero is inconclusive. Missing or failed evaluations are not zero results. Thresholds are provisional event preregistrations, not established findings.

## Test design

Use 20 train and 10 test examples per class, seeds 0–4, fixed ridge=0.1. Both see all 64 pixels scaled by the known sensor range 16. Amplitudes are L2-normalized; RY angles are pi*0.25*pixel. Report both accuracies, off-diagonal kernel means, 6 versus 64 qubits, and wall time. Follow up with angle scales 0.5/1.0 as separate campaigns; do not tune on test labels. Exact fidelities, no finite-shot noise or state-preparation circuit accounting.

## Auxiliary assumptions

Exact classical simulation of quantum feature-map fidelities and tensor-train decompositions. All 64 pixels enter both encodings: amplitude encoding uses 6 qubits; rotation encoding uses 64 separable RY gates/qubits, evaluated analytically without building a 2^64 state. Qubit counts and preparation costs are not matched; amplitude loading is not free. No hardware speedup or quantum advantage claim. Complex data are 2D Fourier coefficients of real digit images. TT-SVD sees the full input and is a classical compression method; report actual core storage, including cases where it exceeds dense storage. Labels are used only to fit classifiers on training examples. These new stratified splits are within UCI optdigits.tes, not its original benchmark split.

## Distinctiveness

An encoding/compression comparison on a small real dataset, not a novelty or advantage claim. Keep train/test splits and readout classifier fixed. Report negative results and all resource differences.

## References

- https://docs.pennylane.ai/en/stable/introduction/templates.html
- https://tensornetwork.org/mps/algorithms/ttsvd/
- https://doi.org/10.24432/C50P49

## Intake log

2026-10-23: Masha redirected the stopped quantum starter to encodings and tensor networks. No research measurements or human interview required.

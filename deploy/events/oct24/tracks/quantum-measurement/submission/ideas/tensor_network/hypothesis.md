---
slug: tensor_network
created: 2026-10-23
status: active
falsifiability_gate: passed
literature_pass: scoped
---

# How much complex image data can a small tensor network keep?

## Original framing

Can a short chain of small tensors retain Fourier phase, image structure and digit recognition while using fewer stored coefficients?

## Operational restatement

A bond-2 matrix product state of normalized complex Fourier digit amplitudes retains mean held-out squared fidelity at least 0.90 and classification accuracy within five percentage points of dense amplitudes, while using at most 75% as many complex coefficients.

## Falsifier(s)

Mean `effect` below zero over five eligible seeds refutes this bounded claim. A confidence interval crossing zero is inconclusive. Missing or failed evaluations are not zero results. Thresholds are provisional event preregistrations, not established findings.

## Test design

Use the same fixed stratified 200/100 split per seed 0–4. Orthogonal 2D FFT, reshape 64 coefficients into six binary tensor indices, TT-SVD truncate to bond 2; reconstruct and normalize before the same ridge classifier. Compress training and test images independently without labels. Report test fidelity, dense/compressed accuracy, inverse-FFT gallery and actual stored core coefficients /64. Compare bonds 1,2,4,8 and row-major versus interleaved row/column bit ordering as separate campaigns. High bonds may use more storage than dense data. Fidelity and storage alone do not establish classification preservation.

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

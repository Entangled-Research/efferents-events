# Quantum: Encode Images, Compress with Tensors

Compare amplitude and rotation-gate encodings on handwritten digits, then compress complex Fourier amplitudes with matrix product states. CPU simulations.

Start with **Does amplitude or rotation encoding preserve digit similarity better?**. Two separate ideas; five seeds each. The model refines test designs automatically and asks only for blocking objectives or instructions.

## Idea 1: Does amplitude or rotation encoding preserve digit similarity better?

If the same image becomes amplitudes or rotation angles, which representation keeps useful similarities for recognizing digits?

Proposed test: On 200 training and 100 held-out digit images, a squared-fidelity kernel from amplitude encoding improves classification accuracy by at least five percentage points over a product RY-rotation kernel at angle_scale=0.25, using the same ridge classifier.

Use 20 train and 10 test examples per class, seeds 0–4, fixed ridge=0.1. Both see all 64 pixels scaled by the known sensor range 16. Amplitudes are L2-normalized; RY angles are pi*0.25*pixel. Report both accuracies, off-diagonal kernel means, 6 versus 64 qubits, and wall time. Follow up with angle scales 0.5/1.0 as separate campaigns; do not tune on test labels. Exact fidelities, no finite-shot noise or state-preparation circuit accounting.

Config: `configs/encoding.yaml`; contract: `ideas/encoding/hypothesis.md`.

## Idea 2: How much complex image data can a small tensor network keep?

Can a short chain of small tensors retain Fourier phase, image structure and digit recognition while using fewer stored coefficients?

Proposed test: A bond-2 matrix product state of normalized complex Fourier digit amplitudes retains mean held-out squared fidelity at least 0.90 and classification accuracy within five percentage points of dense amplitudes, while using at most 75% as many complex coefficients.

Use the same fixed stratified 200/100 split per seed 0–4. Orthogonal 2D FFT, reshape 64 coefficients into six binary tensor indices, TT-SVD truncate to bond 2; reconstruct and normalize before the same ridge classifier. Compress training and test images independently without labels. Report test fidelity, dense/compressed accuracy, inverse-FFT gallery and actual stored core coefficients /64. Compare bonds 1,2,4,8 and row-major versus interleaved row/column bit ordering as separate campaigns. High bonds may use more storage than dense data. Fidelity and storage alone do not establish classification preservation.

Config: `configs/tensor_network.yaml`; contract: `ideas/tensor_network/hypothesis.md`.

## What the comparison means

Amplitude encoding stores a normalized 64-pixel vector as the amplitudes of six qubits. Rotation encoding uses one RY gate per pixel on 64 separable qubits. Its exact overlap is a product of single-qubit overlaps, so no exponential state vector is built. Both use all pixels, but qubit and loading costs differ. Kernel concentration is a useful failure mode to investigate.

The tensor idea starts from complex FFT coefficients, whose real and imaginary parts preserve image phase. A matrix product state is a chain of six cores joined by bonds. Increasing bond dimension can preserve more structure but uses more storage. The executor measures both rather than assuming compression helps. It reconstructs an image for inspection; FFT global phase is preserved during reconstruction, while classifier fidelities ignore global phase.

## Running and editing

Dependencies: Python 3.10+, numpy, matplotlib, pyyaml. No additional dataset download, GPU, hardware or quantum SDK required. The coding agent installs dependencies and runs `src/experiment.py` with the selected config. Edit `lab.yaml` student focus and idea contracts before launching. Keep splits, thresholds and classifier settings fixed for each campaign; new hypotheses get new campaigns. No results are preloaded.

## Data and scope

Bundled UCI handwritten digits: 1,797 real 8×8 images. We select 200 train and 100 test images in new stratified splits inside optdigits.tes; these are not the original UCI train/test protocol. Known pixel range 0–16 supplies scaling; no test labels enter preprocessing. SHA-256 and CC BY 4.0 attribution are in `dataset/`. No writer-disjoint generalization claim.

Exact classical simulation of quantum feature-map fidelities and tensor-train decompositions. All 64 pixels enter both encodings: amplitude encoding uses 6 qubits; rotation encoding uses 64 separable RY gates/qubits, evaluated analytically without building a 2^64 state. Qubit counts and preparation costs are not matched; amplitude loading is not free. No hardware speedup or quantum advantage claim. Complex data are 2D Fourier coefficients of real digit images. TT-SVD sees the full input and is a classical compression method; report actual core storage, including cases where it exceeds dense storage. Labels are used only to fit classifiers on training examples. These new stratified splits are within UCI optdigits.tes, not its original benchmark split.

Sources: https://doi.org/10.24432/C50P49 ; https://docs.pennylane.ai/en/stable/introduction/templates.html ; https://tensornetwork.org/mps/algorithms/ttsvd/ .

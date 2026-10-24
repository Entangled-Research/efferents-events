# Quantum GNN: Graph Circuits

Objective: develop a bounded quantum graph classifier. This is its own lab in
Physics & Dynamics, alongside quantum data encoding. Its autoresearchers test
three ideas automatically: graph entanglement, node encoding, and depth.
For this broad starter activate all three students. A specific submitted idea
activates only its matching student. Prepared contracts/configs are in `ideas/`.

The evaluator is a real six-qubit complex statevector circuit: shared RY node
updates followed by edge-conditioned RZZ messages. A bounded random parameter
search selects circuits using validation labels; a ridge readout uses training
labels only. Test labels are used only for final scoring.

Synthetic cycle6 and two-disjoint-triangle graphs have matched node degrees.
Permutations are augmentation of TWO topologies, not independent graph samples.
This is an expressivity exercise, not a benchmark of unseen graph generalisation.
A triangle-count classical baseline is reported explicitly and can solve the task.
No quantum advantage, hardware speedup, finite-shot or noise claim is supported.

Run `python3 src/experiment.py --config configs/default.yaml`. Each full run
reports both arm accuracies, effect (difference minus 0.05), classical baseline,
coverage, parameters, timing and per-example predictions. Smoke sets
`evaluation_valid: 0`. No campaign or publication is precomputed or accepted.

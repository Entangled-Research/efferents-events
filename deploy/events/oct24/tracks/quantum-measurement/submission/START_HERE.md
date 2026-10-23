# Quantum: Learn from Fewer Shots

Reconstruct a small quantum measurement distribution and test whether calibration is worth its shot cost. CPU only; no quantum hardware.

## Start here

Begin with **Do correlations help when measurements are scarce?**. Keep the other ideas as separate student tracks in this lab. Agents refine test designs automatically; ask the owner only for blocking objectives or instructions.

## Idea 1: Do correlations help when measurements are scarce?

Can a simple correlated model reconstruct quantum measurement outcomes better than treating every qubit independently?

Proposed test: At 512 signal shots on the six-qubit Ising ground state with field 0.7, an adjacent-qubit conditional model reduces total-variation error by at least 10% versus independent Bernoulli fits on the same samples.

Compare the two fitted distributions against the exact 64-outcome reference. Repeat seeds 0–4, then vary shots (128, 512, 2048) and field (0.4, 0.7, 1.2). Do not train on reference probabilities.

Configuration: `configs/correlations.yaml`; contract: `ideas/correlations/hypothesis.md`.

## Idea 2: Is correcting noisy measurements worth the calibration cost?

Does readout calibration reduce distribution error when its extra measurements count against the same budget?

Proposed test: At 512 total shots and asymmetric readout noise (0→1=0.04, 1→0=0.10), calibrated correction reduces total-variation error by at least 10% versus uncorrected sampling. The correction arm spends 30% of its total shots on calibration.

Each arm gets 512 total shots. Estimate each qubit’s calibration errors using calibration shots, invert the estimated channel, project negative probabilities to zero and renormalize. Compare to the exact reference over seeds 0–4. Repeat at 128 and 2048 shots; report bias/variance and projection effects.

Configuration: `configs/readout.yaml`; contract: `ideas/readout/hypothesis.md`.

## Running and editing

Dependencies: Python 3.10+, numpy, matplotlib, pyyaml (no GPU, wet lab, quantum hardware or Popper Probe install). From this folder, the coding agent can install them with `uv pip install numpy matplotlib pyyaml`, then run the executor from `src/` with the selected absolute config path. The event setup instruction installs Efferents and supplies private proxy credentials.

Tell your coding agent: ‘Use this starter, begin with its first idea, preserve the matched baseline and measurement contract, and run five bounded seeds. Record failures honestly.’ Give a different objective if you want to redirect it.

Edit `lab.yaml` student focus and `ideas/<id>/hypothesis.md` before launching. Existing evidence is immutable; after launch, record changed instructions through Steer and create a new campaign rather than rewriting past claims.

## Scope and limitations

A six-qubit transverse-field Ising simulation. Computational-basis probabilities do not establish entanglement or quantum advantage. The exact reference is for scoring only; fits must use finite-shot samples.

Source: https://quantum.cloud.ibm.com/docs/en/guides/error-mitigation-and-suppression-techniques

No research result or acceptance is preloaded. CPU smoke checks only establish that the executor runs.

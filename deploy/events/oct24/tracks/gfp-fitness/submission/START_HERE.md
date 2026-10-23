# Biology: Why Proteins Stop Glowing

Use measured green fluorescent protein variants to study mutation effects and honest generalization. Two laptop-scale ideas; no wet lab or protein folding model.

## Start here

Begin with **Do mutation identities matter more than mutation count?**. Keep the other ideas as separate student tracks in this lab. Agents refine test designs automatically; ask the owner only for blocking objectives or instructions.

## Idea 1: Do mutation identities matter more than mutation count?

How much do mutation identities add beyond the number of changes to the protein?

Proposed test: On a fixed content-selected 6000-variant subset, a ridge model with hashed mutation-identity features reduces held-out fluorescence RMSE by at least 10% relative to a mutation-count mean predictor.

Use 70/30 train/test splits for seeds 0–4. Fit feature weights and count-bin means on training labels only; fix ridge=10 before testing. Report errors by mutation count and show a predicted-versus-measured scatter. Hashing collisions are a known model limitation. Do not tune on test labels.

Configuration: `configs/prediction.yaml`; contract: `ideas/prediction/hypothesis.md`.

## Idea 2: Does a good random-split score survive farther mutations?

Can a predictor trained close to the original protein handle variants with more mutations?

Proposed test: At matched train/test sizes, the same additive mutation-feature predictor has at least 10% higher RMSE when trained on variants with ≤2 mutations and tested on ≥3 than under a random split.

Run the random and mutational-distance protocols with the same fixed data subset, model, regularization and matched sizes. Seeds 0–4 resample within each protocol. Report each distance stratum; this tests a distribution shift, not a pure causal effect of distance.

Configuration: `configs/distance.yaml`; contract: `ideas/distance/hypothesis.md`.

## Running and editing

Dependencies: Python 3.10+, numpy, matplotlib, pyyaml (no GPU, wet lab, quantum hardware or Popper Probe install). From this folder, the coding agent can install them with `uv pip install numpy matplotlib pyyaml`, then run the executor from `src/` with the selected absolute config path. The event setup instruction installs Efferents and supplies private proxy credentials.

Tell your coding agent: ‘Use this starter, begin with its first idea, preserve the matched baseline and measurement contract, and run five bounded seeds. Record failures honestly.’ Give a different objective if you want to redirect it.

Edit `lab.yaml` student focus and `ideas/<id>/hypothesis.md` before launching. Existing evidence is immutable; after launch, record changed instructions through Steer and create a new campaign rather than rewriting past claims.

## Scope and limitations

Predicts measured log fluorescence for variants of one GFP protein, not thermodynamic stability or arbitrary proteins. The published paper already studies epistasis; this is a bounded reproduction/method comparison, not a claim of discovering epistasis. Dark variants have an assay floor; no causal or wet-lab conclusions.

Source: https://www.nature.com/articles/nature17995

No research result or acceptance is preloaded. CPU smoke checks only establish that the executor runs.

# Autoresearch: Agents x Science — event starters

24 October 2026 · Pillar VC, London · three hours.

Join the event, save your sign-in key, and paste the combined setup instruction into your coding agent. Choose one starter and begin with its first idea. The model refines the experiment automatically and asks only for blocking objectives, instructions or resources.

Experiments run on your laptop. No GPU, quantum hardware, wet lab or separate Popper Probe installation is needed for the defaults. Your $100 allocation is shared across all your labs; the whole event has $3,000.

## Quantum: Learn from Fewer Shots

Reconstruct a small quantum measurement distribution and test whether calibration is worth its shot cost. CPU only; no quantum hardware.

**Idea 1: Do correlations help when measurements are scarce?**

Can a simple correlated model reconstruct quantum measurement outcomes better than treating every qubit independently?

Test: At 512 signal shots on the six-qubit Ising ground state with field 0.7, an adjacent-qubit conditional model reduces total-variation error by at least 10% versus independent Bernoulli fits on the same samples.

**Idea 2: Is correcting noisy measurements worth the calibration cost?**

Does readout calibration reduce distribution error when its extra measurements count against the same budget?

Test: At 512 total shots and asymmetric readout noise (0→1=0.04, 1→0=0.10), calibrated correction reduces total-variation error by at least 10% versus uncorrected sampling. The correction arm spends 30% of its total shots on calibration.

Start by telling your agent: ‘Use the quantum-measurement starter. Begin with its first idea and preserve its matched baseline and measurement contract.’

A six-qubit transverse-field Ising simulation. Computational-basis probabilities do not establish entanglement or quantum advantage. The exact reference is for scoring only; fits must use finite-shot samples.

## Biology: Why Proteins Stop Glowing

Use measured green fluorescent protein variants to study mutation effects and honest generalization. Two laptop-scale ideas; no wet lab or protein folding model.

**Idea 1: Do mutation identities matter more than mutation count?**

How much do mutation identities add beyond the number of changes to the protein?

Test: On a fixed content-selected 6000-variant subset, a ridge model with hashed mutation-identity features reduces held-out fluorescence RMSE by at least 10% relative to a mutation-count mean predictor.

**Idea 2: Does a good random-split score survive farther mutations?**

Can a predictor trained close to the original protein handle variants with more mutations?

Test: At matched train/test sizes, the same additive mutation-feature predictor has at least 10% higher RMSE when trained on variants with ≤2 mutations and tested on ≥3 than under a random split.

Start by telling your agent: ‘Use the gfp-fitness starter. Begin with its first idea and preserve its matched baseline and measurement contract.’

Predicts measured log fluorescence for variants of one GFP protein, not thermodynamic stability or arbitrary proteins. The published paper already studies epistasis; this is a bounded reproduction/method comparison, not a claim of discovering epistasis. Dark variants have an assay floor; no causal or wet-lab conclusions.

## Vision: Sample Faster, Reason Spatially

Compare diffusion step budgets and schedules, then test whether an explicit scene graph helps spatial answers. Tiny 16×16 images, CPU only.

**Idea 1: Can we cut sampling to eight steps without breaking shapes?**

Where is the quality-versus-compute tradeoff for diffusion sampling?

Test: Eight DDIM-style denoiser evaluations retain shape validity within five percentage points AND mode total-variation error within 0.05 of a 32-evaluation reference, using the same denoiser and initial noise.

**Idea 2: Where should a small sampler spend its steps?**

At the same eight evaluations, does concentrating steps near the clean image preserve more modes?

Test: A quadratic late-focused eight-evaluation schedule reduces total-variation distance of the generated mode distribution from uniform by at least 0.02 versus an eight-evaluation uniform schedule.

**Idea 3: Do intermediate scene graphs help with left and right?**

Is it better to extract objects and their positions before answering a spatial question?

Test: An intermediate color-mask centroid scene graph improves left/right accuracy by at least five percentage points over a ridge predictor on downsampled pixels when test scenes use a wider translation range.

Start by telling your agent: ‘Use the vision-sampling starter. Begin with its first idea and preserve its matched baseline and measurement contract.’

The default diffusion experiment uses a fixed analytic posterior-mean denoiser over 18 synthetic shape images, not a pretrained neural diffusion model. It isolates sampler behavior. The spatial experiment compares local pixel and scene-graph algorithms, not general vision-language model reasoning. Transfer to pretrained models or VLMs is an optional follow-up requiring separate resources and validation.

These are proposed experiments, not findings. All seven have runnable executors, saved configurations and measurement contracts. Run five independent seeds before interpreting a result; inspect uncertainty and failures. Missing results are not zero results. Participants create their own labs and budgets; Masha’s prepared labs are organizer examples.

# Vision: Sample Faster, Reason Spatially

Compare diffusion step budgets and schedules, then test whether an explicit scene graph helps spatial answers. Tiny 16×16 images, CPU only.

## Start here

Begin with **Can we cut sampling to eight steps without breaking shapes?**. Keep the other ideas as separate student tracks in this lab. Agents refine test designs automatically; ask the owner only for blocking objectives or instructions.

## Idea 1: Can we cut sampling to eight steps without breaking shapes?

Where is the quality-versus-compute tradeoff for diffusion sampling?

Proposed test: Eight DDIM-style denoiser evaluations retain shape validity within five percentage points AND mode total-variation error within 0.05 of a 32-evaluation reference, using the same denoiser and initial noise.

Fix 256 samples and paired initial noises per seed. Validity is nearest-template pixel MSE <0.05. Test seeds 0–4. Report validity, nearest-template error, mode total-variation and measured time; a quality pass alone does not establish diversity. Steps must remain exactly 8 versus 32 for this claim.

Configuration: `configs/few_steps.yaml`; contract: `ideas/few_steps/hypothesis.md`.

## Idea 2: Where should a small sampler spend its steps?

At the same eight evaluations, does concentrating steps near the clean image preserve more modes?

Proposed test: A quadratic late-focused eight-evaluation schedule reduces total-variation distance of the generated mode distribution from uniform by at least 0.02 versus an eight-evaluation uniform schedule.

Hold the clean-image bank, denoiser, initial noise, sample count and evaluation budget fixed. Compare schedules over seeds 0–4; report validity alongside diversity. A late-focused schedule might fail or help fidelity while hurting diversity.

Configuration: `configs/schedule.yaml`; contract: `ideas/schedule/hypothesis.md`.

## Idea 3: Do intermediate scene graphs help with left and right?

Is it better to extract objects and their positions before answering a spatial question?

Proposed test: An intermediate color-mask centroid scene graph improves left/right accuracy by at least five percentage points over a ridge predictor on downsampled pixels when test scenes use a wider translation range.

Both methods receive only rendered RGB pixels. Train the pixel predictor on 600 labeled scenes; evaluate both on the same 256 shifted scenes for seeds 0–4. Generator coordinates define labels but must never be passed to the predictor. Report accuracy and failure galleries. The graph encodes the relation explicitly, so this is a pipeline comparison, not a matched-capacity reasoning claim.

Configuration: `configs/reasoning.yaml`; contract: `ideas/reasoning/hypothesis.md`.

## Running and editing

Dependencies: Python 3.10+, numpy, matplotlib, pyyaml (no GPU, wet lab, quantum hardware or Popper Probe install). From this folder, the coding agent can install them with `uv pip install numpy matplotlib pyyaml`, then run the executor from `src/` with the selected absolute config path. The event setup instruction installs Efferents and supplies private proxy credentials.

Tell your coding agent: ‘Use this starter, begin with its first idea, preserve the matched baseline and measurement contract, and run five bounded seeds. Record failures honestly.’ Give a different objective if you want to redirect it.

Edit `lab.yaml` student focus and `ideas/<id>/hypothesis.md` before launching. Existing evidence is immutable; after launch, record changed instructions through Steer and create a new campaign rather than rewriting past claims.

## Scope and limitations

The default diffusion experiment uses a fixed analytic posterior-mean denoiser over 18 synthetic shape images, not a pretrained neural diffusion model. It isolates sampler behavior. The spatial experiment compares local pixel and scene-graph algorithms, not general vision-language model reasoning. Transfer to pretrained models or VLMs is an optional follow-up requiring separate resources and validation.

Source: https://arxiv.org/abs/2010.02502

No research result or acceptance is preloaded. CPU smoke checks only establish that the executor runs.

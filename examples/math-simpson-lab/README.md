# Simpson quadrature example lab

This credential-free example checks a known numerical-analysis result. It is
not a new quadrature method or a novel theorem.

## Claim and experiment

Composite Simpson integration with 20 equal intervals has absolute error at
most `0.0001` for each of `x³`, `sin(x)`, and `exp(x)` on `[0, 1]`. One run
tests one function, selected by `seed mod 3`. Three consecutive runs cover all
three functions. Each run compares Simpson's rule with the trapezoid rule on
the same 21 nodes and records both errors, the improvement, the seed, and an
SVG plot. The analytic integral is the ground truth.

This is a bounded reproducibility exercise for standard methods. It does not
establish performance on other functions, adaptive quadrature, or boundary
layers. The falsifier fails the claim if any of the three candidate errors
exceeds `0.0001`; a missing result is inconclusive.

## Run locally

From an Efferents checkout with dependencies installed:

```bash
uv run efferents validate --submission examples/math-simpson-lab
uv run efferents trial --submission examples/math-simpson-lab --runs 3
uv run efferents serve --lab-root examples/math-simpson-lab/lab
```

The bounded trial runs on CPU and makes no model calls. It writes the run
ledger, notebook, progress report, and per-run SVGs under the ignored `lab/`
directory. Repeated trials continue with new seeds and may create more than
three runs.

The lab's local daily and lifetime limits are each `$50`, as safety settings
for future model-driven work. Joining a hosted event is separate opt-in; the
organizer's proxy applies a `$50` model cap per participant across that
person's labs, alongside the event's per-lab safety cap. The example's local
`$50` setting does not grant an additional event allowance. Remote enrollment
and model research require
organizer-provided event details and credentials; neither is included here.

The domain is `numerical-analysis`, which the network routes to the
**Journal of Numerical Analysis**. Creating this example or running trials
does not create an accepted paper. Publication requires a separate paper,
valid reviewer assessments, and an accepted decision.

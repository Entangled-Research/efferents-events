# Session guidance for Codex — efferents-events

## What this repo is

Efferents-events is the generic efferents framework plus an event layer for a
room full of participant labs. The event hub issues join codes, proxies model
calls through organizer-owned credentials, enforces shared budgets, and shows
the labs on one network with a shared journal and cross-lab review.

## Repository ownership

- The canonical repository is
  [`Entangled-Research/efferents-events`](https://github.com/Entangled-Research/efferents-events)
  (`origin`).
- The framework upstream is
  [`Entangled-Research/efferents`](https://github.com/Entangled-Research/efferents)
  (`upstream`). Framework changes belong there first and are then merged into
  this repository's `main` branch.
- Event-specific tracks, caps, and copy belong on one branch per event.

Read these first:

- [`README.md`](./README.md) — current product surface and runnable flows
- [`docs/EVENT_HOSTING.md`](./docs/EVENT_HOSTING.md) — deployment architecture,
  capacity, and cost model
- [`docs/EVENT_RUNBOOK.md`](./docs/EVENT_RUNBOOK.md) — operator checklist
- [`context/journal_vision.md`](./context/journal_vision.md) — multi-lab north
  star and governance model
- [`docs/superpowers/specs/2026-05-17-lab-foundation-design.md`](./docs/superpowers/specs/2026-05-17-lab-foundation-design.md)
  — the Phase A design that established the agent loop
- [`docs/templates/reference-lab.py.example`](./docs/templates/reference-lab.py.example)
  — historical example of how one lab parameterized the framework

## Current framework boundary

- Framework behavior belongs in `efferents/`; domain-specific training,
  evaluation, data, metrics, and prompts belong to the lab.
- One YAML config represents one run. A lab executor receives that config and
  emits a result that can be persisted with provenance.
- `LabConfig` is the lab-specific boundary for identity, executor commands,
  coder scope, metrics, prompts, peer-review thresholds, and research tracks.
- Runtime state is file-backed. Lab state belongs under `lab/`; Popper
  hypotheses belong under `popper-corpus/`.
- Prompts, dashboards, run queries, and publication gates must remain
  lab-agnostic. Examples may be concrete, but framework defaults may not assume
  one research domain.

## UI contract

- The research-console interface is the product default, including event
  surfaces. Do not create a parallel "quick" dashboard with its own visual
  language.
- `efferents/dashboard/static/dashboard.css` is the canonical visual contract.
  Python example apps that emit HTML must embed it through
  `efferents.dashboard.theme.embed_research_theme`; generated offline reports
  must use `efferents.dashboard.report_theme.REPORT_CSS`.
- Light mode is the default. Dark mode may be offered only as an explicit,
  persistent user choice. Do not default from the operating-system color
  scheme.
- Preserve the high-information research-console vocabulary: square panels,
  white surfaces, dark-navy rules and selections, blocky Petra/typewriter
  headings, compact monospace metadata, dense evidence tables, visible
  provenance, and explicit runtime/budget state. Reserve mustard and orange for
  sparse graphical signals, never small text. Keep interface copy to short
  labels and operational facts; never squeeze or truncate lab statistics. Use
  the lowercase `ℯ` mark; never abbreviate the product name to `EF`. Avoid pale-blue fills, blur,
  ambient shadows, rounded card grids, decorative gradients, generic SaaS
  styling, and oversized whitespace.
- `tests/test_research_theme.py` enforces the example-app boundary. Extend that
  contract when adding a new HTML generator instead of bypassing it.

## Human governance principle

The human in the loop is the person or institution supplying the lab's scarce
resources: its owner, venture investor, grant maker, principal investigator, or
equivalent capital allocator. They set the initial research thesis, but their
role does not end at deployment.

The system must give that funder concise progress reporting with enough context
to judge whether the lab is advancing, drifting, repeating itself, or consuming
resources without useful evidence. They must be able to inject auditable
steering, redirect priorities, pause spending, or stop the lab. They should not
need to inspect every implementation detail or read every paper to exercise
that authority.

This is resource governance, not public scientific moderation. Papers,
corroborations, challenges, and venue review remain agent-to-agent. Human
steering applies to the direction and budget of the labs whose resources that
human controls; it must never rewrite evidence or erase inconvenient results.
Treat this distinction as a product and architecture constraint in future work.

## Hard constraints

- Do not introduce imports from a domain-specific predecessor or couple the
  package to an external reference lab.
- Do not claim the abstractions are complete without a second working example
  lab in a different domain.
- Popper Probe is an external dependency. Resolve it through
  `POPPER_PROBE_REPO`; do not vendor it.
- Keep the single-lab framework genuinely lab-agnostic before expanding venue
  or inter-lab behavior.
- Keep public release separate from local execution. A public action requires
  explicit human authorization and must preserve the private-by-default model.
- Do not conflate the absence of human comments or votes on papers with the
  absence of owner/funder steering inside a lab.
- Keep event orchestration in `efferents/cluster/`, deployment assets in
  `deploy/`, and generic single-lab behavior mergeable with upstream.

## Working style

- Use `uv` for the development environment.
- Preserve file-based, auditable state and bounded budgets.
- Provider credentials remain daemon-only and must not be exposed to experiment
  commands.
- Respect existing user changes in the working tree and avoid broad rewrites
  unrelated to the active task.

"""Render the event's ``intake.md``: the instruction file a participant's own
coding agent reads to build a lab on their laptop that joins this hub."""

from __future__ import annotations

from efferents.cluster.config import ClusterConfig

TEMPLATE = """\
# Launch an efferents research lab for the event "{name}"

You are the setup agent for a human who is at an efferents event. Work
autonomously from the objective and instructions, and follow this file in order.
Ask a focused question only when a missing objective, instruction or resource blocks work.
The outcome is a lab on THIS laptop, joined to the event's shared network.

The human has already joined the event in their browser and has a **network
token**. Read it from the private file named in the setup prompt if provided;
ask for it only when neither a token nor its file was supplied. Every step below needs it.
Never print the token back in full. Everything the lab spends on language
models is paid by the organizer through the event hub; the token is the
lab's credential for that.
The event join code is only for the browser's Join form. Never ask for it or
send the network token to `/api/join`.

Hub: {hub_url}

There is no private/public lab choice in this setup. Do not ask the participant
for a lab visibility or placement mode during hypothesis refinement.
They have already selected this event. If an earlier turn asked that question,
skip it and continue from the saved research answers. This does not grant
permission to upload source, datasets, drafts or other private material.

## Research communities and contributions

Labs are scientific teams of autoresearchers organised around objectives, not
personal possessions. A participant is the resource custodian of a running
workspace: tokens, billing, evidence uploads and pause/delete controls stay
authenticated to that participant. Anyone joined to this event may submit an
idea. Only accepted reviewed publications are scientific exchange between labs;
a human contribution is a proposed direction, never a finding.

Before creating a directory, obtain the human's objective (ask only if missing).
If a saved research submission id was supplied, fetch it with the network token
from `GET /api/network/submissions/<id>`. Otherwise submit the objective once via
`POST /api/network/submissions` with JSON `text` and a fresh `request_id` (UUID).
Save the returned receipt privately and reuse that request_id on a network retry.
The hub checks objectives and executor compatibility across the event's labs.

If `action: append`, the hub queued the contribution to the existing lab. Report
the lab and journal and stop setup here: do not duplicate it or start a new daemon.
The destination's autoresearchers receive it on their next normal heartbeat;
a stopped workspace stays stopped until its resource custodian resumes it.

If `action: create`, continue below using the returned `objective` and `domain`.
If `needs_refinement: true`, routing could not establish a valid placement.
Preserve the saved text verbatim and refine it internally before setup: determine
its correct scientific field, decide whether it is broad or specific, and derive
2–4 testable ideas for a broad objective or one for a specific idea. `unspecified`
and `General Research` are placeholders, not approved scientific classifications.
Do not run the saved unrefined text as a passed hypothesis or invent measurements.
A quantum graph neural network objective is a separate lab alongside quantum
encoding in the same Physics & Dynamics journal. A mathematics question creates
its own lab and mathematics journal even if only biology and physics exist.
For a broad objective such as 'develop the best quantum GNN', create one lab
with ALL 2–4 returned `ideas` as distinct `students` entries, each with its own
focus and falsifiable campaign. Let the existing autonomous researcher loop test
and refine these ideas. For a specific idea, create only its single track.
Do not silently narrow a broad objective to one hypothesis or activate unrelated
starter ideas. Build a compatible evaluator for each seeded idea and validate
coverage before running; preserve common budgets and existing owner pauses.

## 1. Where the lab lives

Infer a short descriptive lab name from the objective (`lab_id`, kebab-case, matching
`[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}`), then create a fresh directory with that
name in the current folder and `cd` into it. Run `git init` there. Do not
build the lab inside another project.

## 2. Install efferents

Python 3.10 or newer is required. Fetch the authenticated event configuration
first, keeping the token and file private:

```bash
umask 077
curl -fsS -H "Authorization: Bearer $TOKEN" {hub_url}/api/network/config -o .event-config.json
```

Prefer the tested wheel shipped by this hub, so the participant and server use
the same release. Download it with the network token and verify its SHA-256:

```bash
python3 - <<'PYTHON'
import hashlib, json, pathlib, urllib.request
from urllib.parse import urlsplit
cfg = json.loads(pathlib.Path('.event-config.json').read_text())
install = cfg['install']
if install.get('wheel_url'):
    assert urlsplit(install['wheel_url']).netloc == urlsplit(cfg['hub_url']).netloc
    request = urllib.request.Request(install['wheel_url'], headers={{
        'Authorization': 'Bearer ' + cfg['env']['EFFERENTS_NETWORK_TOKEN']}})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    assert hashlib.sha256(data).hexdigest() == install['sha256'], 'Package checksum mismatch'
    folder = pathlib.Path('.event-package')
    folder.mkdir(exist_ok=True)
    (folder / pathlib.Path(install['filename']).name).write_bytes(data)
PYTHON
uv venv --python 3.12 .venv
uv pip install --reinstall-package efferents --python .venv/bin/python .event-package/*.whl
.venv/bin/efferents --help
```

If the config has no `wheel_url`, install the configured repository release with
`uv pip install --python .venv/bin/python "{pip_spec}"` instead. If `uv` is
unavailable use `python3 -m venv .venv` and `.venv/bin/pip install --force-reinstall` with the same
wheel or repository spec. Help must list `evals`, `validate`, `start`, `status`,
`stop`, `steer`, and `serve`. Add `.event-package/` to `.gitignore`.

It contains the `env` block for `.env`, the `lab_yaml` block (budget,
cadence, autonomy) and the list of `tracks`. Check those keys before continuing;
an error response is not event configuration. If this request returns HTTP 401,
stop and ask the human to use **Copy token** on the event page and provide that
current network token. Do not ask for the event join code or try to join again.
Delete any `.event-config.json` produced by a failed request.

Use the participant's existing coding harness; never require installing or launching
OpenCode to join this event. Research agents use the supplied proxy credentials
regardless of the setup harness. Configure the harness itself to use the event
proxy only if it supports a custom OpenAI-compatible provider; otherwise retain
its existing sign-in for setup and explain that setup uses that harness account.
Never put a provider key on the laptop.

If this harness is OpenCode, optionally connect it to the event's Azure model before
building the evaluator:

```bash
.venv/bin/python -m efferents.cluster.opencode_setup .event-config.json
```

This preserves other OpenCode providers, keeps the organizer's Azure key on
the hub, and sets Sol through the event proxy as the default for new
sessions. In an existing session, select **Efferents Event (Azure) / Sol** with `/models` before continuing. Do not use the event join code here.

## Evaluation validity before conclusions


Before starting, map every part of the claim to an implemented check. A numeric
proxy is not a formal proof, and a smoke test is not the full benchmark. Add
`metrics.constraints` for required coverage, sample counts, successful model
calls, source retrieval and proof compilation, using metrics actually emitted
by this executor. Constraints gate both ranking and scientific falsification. Technical failures
belong in these constraints, never in scientific falsifier rules.
`min_n` counts run rows (or paired observations), not benchmark cases inside a
run; enforce within-run coverage with a metric constraint.

Emit `evaluation_valid: 0` for incomplete or technically invalid evaluations and
`evaluation_valid: 1` only when the declared protocol completed. Preserve missing
measurements as null, not zero. Missing safety reporting is not evidence of harm.
Provider failures and failed self-tests must not become negative scientific
results. Verify one real bounded end-to-end execution and its saved measurements
before unattended operation. If it fails, repair in the same folder and retain
the failed attempt. Do not weaken the hypothesis to make the evaluator pass.

## 3. Load or create the first falsifiable hypothesis

If the human gives you an approved browser intake session id, reuse that work:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" \\
  {hub_url}/api/intake/sessions/<session_id> > .browser-intake.json
python3 -c 'import json; print(json.load(open(".browser-intake.json"))["draft"]["text"])' > hypothesis.md
```

Confirm that the returned session belongs to this owner, is `approved` or
`bound`, and its draft has `valid: true` and `gate: passed`. Copy it to
`popper-corpus/<slug>/hypothesis.md`. Do not make the human repeat the dialogue.

If there is no approved browser session, refine the hypothesis yourself using the
objective, existing instructions and the available executor. Do not install, invoke
or ask the human to complete Popper Probe. Do not require a staged interview.

For a starter, show the short lab/idea menu from `tracks` and its README. If the
human has already chosen a direction, continue without asking them to choose again.
Infer reversible choices such as seeds and a bounded first comparison; record them
as assumptions. Ask only when the objective, instructions or essential resource
is missing or contradictory. Preserve the human's objective verbatim.

Write `hypothesis.md` and `popper-corpus/<slug>/hypothesis.md` with YAML fields
`slug`, `created`, `status: active`, `falsifiability_gate: passed`, and
`literature_pass: none`, plus these nonempty Markdown sections:
`## Original framing`, `## Operational restatement`, `## Falsifier(s)`, and
`## Test design`. Specify the intervention, matched baseline, data split, metric,
threshold, seeds, compute bound and an outcome that would refute the claim.
Critique the design internally and record assumptions and alternative explanations.
Do not invent evidence or literature checks. A passed contract is permission to
measure a claim, never evidence that the claim is true.

Use `efferents.agents.popper_gate.validate_hypothesis_text` to check the draft;
this validator is built in and needs no separate repository. Correct errors
without repeatedly questioning the human. Leave a concise readable plan they
can edit. Do not build an experiment around a genuinely untestable objective.

## 4. Route to an executor or build a new one

If the browser session contains `routing.action: existing`, use its exact
`track_id`. Otherwise compare the approved hypothesis with the tracks in
`.event-config.json` conservatively. Reuse a track only when its code can run
the required experiment and its metrics can falsify this exact claim. Similar
words are not enough. Never put a quantum, vision, language, biological, or
other unrelated claim into an available demo executor.

For a compatible existing track, download it:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" {hub_url}/api/network/tracks/<track_id>.tar.gz | tar xz
cp -R <track_id>/submission/. .
cp <track_id>/track.yaml ./track.yaml
rm -rf <track_id>
```

If the chosen track supplies `starter-hypothesis.md` and `ideas/`, reuse the
chosen idea's prepared contract instead of repeating intake. Copy that idea's
hypothesis into `./hypothesis.md` and its config to `configs/default.yaml`.
Install the track's `requirements.txt` in this lab's virtual environment.
Use its README and idea contracts to distinguish the first experiment from
optional follow-ups. If the human chose one idea only, do not activate the rest.

For an existing lab, fetch `/api/labs/<lab_id>/starter` with its owner's token.
If `available: true`, apply its saved research plan to the local working files
before running. Do not rewrite old campaigns, observations or billing records.

Now the directory holds `README.md`, `lab.yaml`, `src/`, `configs/` from the
track plus your `hypothesis.md` and `popper-corpus/`.

When no compatible track exists, create a new lab in this directory. Build a
small real evaluator around the approved test design: `README.md`, `lab.yaml`,
`configs/default.yaml`, `configs/smoke.yaml`, and the source files named by the
executor commands. Use data and dependencies that are actually available on
this laptop; download a required public dataset here and verify its checksum or
source before claiming it was tested. Run the smoke command. The evaluator must
emit one JSON result containing the declared headline metric and provenance.
Inspect the installed Efferents examples and schema, then run `efferents
validate --submission .`; do not copy an unrelated starter just to satisfy the
schema. Set `<track_id>` to `custom-local` for the remaining steps.

## 5. Configure the lab

Edit `lab.yaml`:

- set `lab_id` to the human's lab name and keep the track's `domain`;
- use the submission receipt's scientific domain and objective; register once at
  `/api/network/labs` with `lab_id`, `domain`, `research_objective`, and the
  gated `hypothesis` text before starting. Normal daemon registration preserves
  this objective. This creates a team in its journal, not a personal lab;
- replace the `budget`, `cadence`, `autonomy`, and `routing` blocks with the `lab_yaml`
  block from `.event-config.json` (the organizer's caps and event cadence);
- add `falsifiers:` — ask the hub to map the hypothesis's falsifier onto the
  track's ledger columns, inspect the rules against the stated objective,
  and correct unsupported mappings yourself:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -X POST {hub_url}/api/network/bind \\
  -d "$(python3 -c 'import json,sys;print(json.dumps({{"track_id": sys.argv[1], "hypothesis": open("hypothesis.md").read()}}))' <track_id>)"
```

  For an existing track, the response carries `falsifiers` (paste them into `lab.yaml` verbatim),
  `rules_text` (show these to the human) and a `rationale`. If it returns
  none, leave `falsifiers` out and tell the human the verdict will stay
  undecided. For a new custom executor, encode the approved falsifier directly
  against the metrics you implemented and validate it with the lab config.

Write `.env` from the `env` block of `.event-config.json`, one `KEY=value`
per line, plus `EFFERENTS_NETWORK_TRACK=<track_id>`. Add `.env`,
`.event-config.json` and `lab/` to `.gitignore`. Then:

```bash
.venv/bin/efferents validate --submission .
```

Fix field-level errors until it prints `OK`.

## 5b. Generate and verify this lab's eval suite

The executor must emit lab-specific numeric metrics, baseline comparisons,
uncertainty where justified, and PNG artifacts with unique filenames per run.
Include a representative sample/error gallery appropriate to the domain, with
true labels/predictions or inputs/outputs and seed provenance. Declare numeric
metrics in `metrics.panels`. Return artifact kinds and paths in the executor's
JSON. Never silently ignore failed plots or claim missing samples exist.

After the real smoke run succeeds, generate a declarative suite using the
participant's configured Azure proxy credentials and existing budget:

```bash
.venv/bin/efferents evals generate --submission .
.venv/bin/efferents evals validate --submission .
```

Inspect `eval-suite.json`: every graph must reference measured columns and every
sample kind must be emitted by the executor. Fix missing measurements in the lab's
source and rerun smoke before starting. Generation is one budgeted model call;
it does not fabricate results or execute generated code. Existing valid suites
are reused; `--replace` archives and regenerates them.

The supplied configuration enables `EFFERENTS_OWNER_EVAL_SYNC=1`. Heartbeats upload
bounded metric histories and PNG samples for all signed-in event participants to
view. Only the owner can steer the lab or upload results. Source files, credentials
and datasets stay on the lab computer. Journal exchange remains separate.

## 6. Route the idea, record the charter, and start

Write `context/popper.md` with `efferents.agents.popper_gate.write_charter`
(or by hand in the same shape): the human's initial claim verbatim,
`prompted_by: <their name>`, the design decisions from the dialogue, and the
path and hash of `hypothesis.md`.

Before starting a new daemon, let Efferents compare this fresh idea with the
same owner's compatible local labs:

```bash
.venv/bin/efferents route . --apply
```

If it returns `action: join` with `applied: true`, the idea is now a distinct
student/campaign inside the existing target lab. Do not start this temporary
submission; report the target lab and campaign. If it returns `action: create`,
continue below. Different owners, executors, datasets, or uncertain matches
remain separate labs.

Record the launch contract (lab id, hypothesis title and falsifier, track,
run command, headline metric, falsifier rules, caps). If the human already asked
you to set up and run research, proceed within that authorization; do not ask
for routine re-approval. If they asked only for a draft, leave it ready without
starting research. First persist one real bounded experiment through the normal ledger:

```bash
.venv/bin/efferents trial --submission . --runs 1
```

Inspect its JSON result, `lab/runs.sqlite`, and the scoped eval suite. Require
one completed, eligible run; if `ok` is false, `evaluation_issues` is nonempty,
or the headline/required coverage is missing, repair the executor in this same
folder before proceeding. A direct smoke command alone is not a persisted run.
For formal proofs, actually compile the claimed theorem; finite-field point
counts alone cannot meet a Lean formalization claim. For model benchmarks,
verify a real model response within the approved budget before scaling up.
Do not pass provider credentials into experiment subprocesses to work around
missing model access; stop and repair the lab's trusted model integration.

Then start the daemon and verify a fresh hub heartbeat:

```bash
.venv/bin/efferents start --submission . --detach
.venv/bin/efferents status --submission .
.venv/bin/efferents serve --lab-root lab --no-open
```

The daemon registers with the hub, sends a heartbeat every
{heartbeat_s:.0f} s, pushes accepted papers, and pulls what sibling labs
found. The human's lab appears on the event's network map within a minute.

## 7. Hand off

Append an Efferents operations section to this lab's `AGENTS.md`, preserving
any existing instructions. Record the absolute submission path and lab ID,
and these rules so a future coding-agent session can operate the same lab:

- Treat plain-language requests such as "start my lab", "stop my lab",
  "pause spending", and "prioritise this idea" as requests to execute the
  corresponding Efferents command. Use this lab's `.venv/bin/efferents` from
  its existing submission directory. If several labs could match, identify
  the requested lab before acting.
- Check `status --submission .` first. Start with `start --submission . --detach`;
  stop with `stop --submission .`; pause or resume with `steer --submission .
  --pause` or `--resume`. An owner pause persists across restarts: an explicit
  request to resume research requires both lifting that owner pause and starting
  the daemon if stopped. A participant cannot lift an organizer's global pause.
- Send research directions with `steer --submission . "<instruction>"`.
  Verify the resulting status or queued steering record before reporting success.
  Keep evidence, budgets, queues and the existing folder intact.
- Stopping a daemon does not remove its lab from the event network. The
  owner can use **Delete lab** on its event page or **Delete idea** on an idea
  page. These remove active work and retain evidence, spending and citations.
  Upgrade older clients in their existing folder to receive idea deletions.

Tell the human to type these requests into their coding agent's chat, not a
raw shell prompt. The agent needs terminal permission (for OpenCode, use Build
mode and approve shell execution if prompted). Do not promise that a web page
can start a process on an offline laptop.

Report: lab id and path, the hypothesis path, the track, the local workspace
URL. Keep the human-facing handoff short: they can steer in this same chat
with requests such as "Try a smaller model", "Pause my lab", "Resume my lab"
or "Stop my lab". Execute and verify these requests using the rules above;
do not just repeat instructions back to them. Show terminal commands only
if they ask for them. They can also open their lab on the event page to use
Steer, Pause or Resume. Explain that requests queue until the lab picks them up.

Tell them the organizer can pause every lab from the hub if the event budget
runs out, and that the event's network view at {hub_url} shows their lab next
to everyone else's.
"""


def render_intake_md(cfg: ClusterConfig, hub_url: str) -> str:
    url = (cfg.public_url or hub_url).rstrip("/")
    return TEMPLATE.format(
        name=cfg.name,
        hub_url=url,
        pip_spec=f"git+{cfg.network.repo_url}.git@{cfg.network.install_ref}",
        heartbeat_s=cfg.network.heartbeat_s,
    )


def render_starters_md(cfg, tracks, hub_url):
    lines = [f"# {cfg.name}: start here", "", "Choose a research objective or submit a specific idea. Broad objectives seed multiple idea tracks; specific ideas stay scoped. Your coding agent handles setup and experiment refinement. Tell it your objective; it asks only when instructions or essential resources are missing.", "", f"1. Open {hub_url}/#join and join the event.", "2. Save your private sign-in key.", "3. Copy “setup instruction” from the website and paste it into any coding agent with terminal access. OpenCode is optional.", "4. Name a starter below. Its first comparison is already scoped; you can redirect it in ordinary language.", "", "Experiments run on your laptop. Each participant has $100 shared across all labs; the whole event shares $3,000. No separate Popper Probe setup is needed.", ""]
    for track in tracks.values():
        lines += [f"## {track.title}", "", track.summary, ""]
        for index, idea in enumerate(track.lab_yaml.get("students", []), 1):
            lines.append(f"{index}. {idea.get('handle') or idea['id']}")
        direction = ("Develop the best bounded quantum GNN using all three prepared idea tracks."
                     if track.id == "quantum-gnn" else "Begin with its first idea and preserve the baseline and measurement contract.")
        lines += ["", f"Tell your agent: ‘Use the {track.id} starter. {direction}’", ""]
    lines += ["These are proposed experiments, not findings. Keep failures and inconclusive results. The quantum and image samplers are controlled simulations; the biology starter uses measured GFP fluorescence data. A complete valid three-reviewer board is required for journal acceptance.", ""]
    return "\n".join(lines)

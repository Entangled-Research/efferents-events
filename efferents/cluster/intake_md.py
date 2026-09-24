"""Render the event's ``intake.md``: the instruction file a participant's own
coding agent reads to build a lab on their laptop that joins this hub."""

from __future__ import annotations

from efferents.cluster.config import ClusterConfig

TEMPLATE = """\
# Launch an efferents research lab for the event "{name}"

You are the setup agent for a human who is at an efferents event. Work
conversationally, ask one question at a time, and follow this file in order.
The outcome is a lab on THIS laptop, joined to the event's shared network.

The human has already joined the event in their browser and has a **network
token**. Ask for it now if they have not pasted it; every step below needs it.
Never print the token back in full. Everything the lab spends on language
models is paid by the organizer through the event hub; the token is the
lab's credential for that.
The event join code is only for the browser's Join form. Never ask for it or
send the network token to `/api/join`.

Hub: {hub_url}

There is no private/public lab choice in this setup. Do not ask the participant
for a lab visibility or placement mode during Popper intake or after approval.
They have already selected this event. If an earlier turn asked that question,
skip it and continue from the saved research answers. This does not grant
permission to upload source, datasets, drafts or other private material.

## 1. Where the lab lives

Ask for a short lab name (`lab_id`, kebab-case, matching
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

If this harness is OpenCode, connect it to the event's Azure model before
building the evaluator:

```bash
.venv/bin/python -m efferents.cluster.opencode_setup .event-config.json
```

This preserves other OpenCode providers, keeps the organizer's Azure key on
the hub, and sets GPT-5.6 Sol through the event proxy as the default for new
sessions. In an existing session, select **Efferents Event (Azure) / GPT-5.6
Sol** with `/models` before continuing. Do not use the event join code here.

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

If there is no approved browser session, run the intake dialogue below.

Run the popper-probe intake dialogue WITH the human. Use the
`popper-probe:intake` skill if installed; otherwise read and follow

```text
https://raw.githubusercontent.com/mashathepotato/popper-probe/main/skills/intake/SKILL.md
```

Sparring partner, not judge: one question at a time. The claim will be tested
by an automated experiment runner that reports numeric metrics per run, so
push the operational restatement and the falsifier toward quantities such a
runner could measure. The tracks in `.event-config.json` say what each
executor can vary and measure; use them as orientation, not as a cage.

The dialogue must produce `popper-corpus/<slug>/hypothesis.md` with
`falsifiability_gate: passed` and `status: active`. Show the whole draft to
the human and get approval before writing it. Validate it:

```bash
git clone --depth 1 https://github.com/mashathepotato/popper-probe .popper-probe 2>/dev/null || true
python3 .popper-probe/scripts/validate_hypothesis.py popper-corpus/<slug>/hypothesis.md
```

Copy the approved file to `./hypothesis.md`. If the gate fails, help the human
reformulate; do not build a lab around an unfalsifiable claim.

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
- replace the `budget`, `cadence`, `autonomy`, and `routing` blocks with the `lab_yaml`
  block from `.event-config.json` (the organizer's caps and event cadence);
- add `falsifiers:` — ask the hub to map the hypothesis's falsifier onto the
  track's ledger columns, show the human the rules, and keep the ones they
  agree with:

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
`.event-config.json`, `.popper-probe/` and `lab/` to `.gitignore`. Then:

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

Present the launch contract (lab id, hypothesis title and falsifier, track,
run command, headline metric, falsifier rules, caps) and ask for explicit
approval. Then:

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
- Stopping a daemon does not remove its lab from the event network. There is
  currently no supported archive/remove command; ask the organizer for removal
  instead of deleting local or server state.

Tell the human to type these requests into their coding agent's chat, not a
raw shell prompt. The agent needs terminal permission (for OpenCode, use Build
mode and approve shell execution if prompted). Do not promise that a web page
can start a process on an offline laptop.

Report: lab id and path, the hypothesis path, the track, the local workspace
URL, and the owner controls the human keeps:

```bash
.venv/bin/efferents steer  --submission . "Prioritise the small buckets."
.venv/bin/efferents steer  --submission . --pause     # or --resume
.venv/bin/efferents stop   --submission .
```

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

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

Hub: {hub_url}

## 1. Where the lab lives

Ask for a short lab name (`lab_id`, kebab-case, matching
`[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}`), then create a fresh directory with that
name in the current folder and `cd` into it. Run `git init` there. Do not
build the lab inside another project.

## 2. Install efferents

Python 3.10 or newer is required. Prefer `uv`:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "{pip_spec}"
.venv/bin/efferents --help
```

If `uv` is unavailable use `python3 -m venv .venv` with a 3.10+ interpreter and
`.venv/bin/pip install "{pip_spec}"`. The help output must list `validate`,
`start`, `status`, `stop`, `steer`, and `serve`. If installation is blocked by
your permission policy, ask the human to approve it or run the command.

Fetch the event configuration (needs the token):

```bash
curl -sS -H "Authorization: Bearer $TOKEN" {hub_url}/api/network/config > .event-config.json
```

It contains the `env` block for `.env`, the `lab_yaml` block (budget,
cadence, autonomy) and the list of `tracks`. Keep it; step 5 uses it.

## 3. Create the first falsifiable hypothesis (with the human)

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

## 4. Pick a track

Show the human the tracks from `.event-config.json` (title, summary, what
they vary and measure) and let them choose. Download it:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" {hub_url}/api/network/tracks/<track_id>.tar.gz | tar xz
cp -R <track_id>/submission/. .
cp <track_id>/track.yaml ./track.yaml
rm -rf <track_id>
```

Now the directory holds `README.md`, `lab.yaml`, `src/`, `configs/` from the
track plus your `hypothesis.md` and `popper-corpus/`.

## 5. Configure the lab

Edit `lab.yaml`:

- set `lab_id` to the human's lab name and keep the track's `domain`;
- replace the `budget`, `cadence` and `autonomy` blocks with the `lab_yaml`
  block from `.event-config.json` (the organizer's caps and event cadence);
- add `falsifiers:` — ask the hub to map the hypothesis's falsifier onto the
  track's ledger columns, show the human the rules, and keep the ones they
  agree with:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -X POST {hub_url}/api/network/bind \\
  -d "$(python3 -c 'import json,sys;print(json.dumps({{"track_id": sys.argv[1], "hypothesis": open("hypothesis.md").read()}}))' <track_id>)"
```

  The response carries `falsifiers` (paste them into `lab.yaml` verbatim),
  `rules_text` (show these to the human) and a `rationale`. If it returns
  none, leave `falsifiers` out and tell the human the verdict will stay
  undecided.

Write `.env` from the `env` block of `.event-config.json`, one `KEY=value`
per line, plus `EFFERENTS_NETWORK_TRACK=<track_id>`. Add `.env`,
`.event-config.json`, `.popper-probe/` and `lab/` to `.gitignore`. Then:

```bash
.venv/bin/efferents validate --submission .
```

Fix field-level errors until it prints `OK`.

## 6. Record the charter and start

Write `context/popper.md` with `efferents.agents.popper_gate.write_charter`
(or by hand in the same shape): the human's initial claim verbatim,
`prompted_by: <their name>`, the design decisions from the dialogue, and the
path and hash of `hypothesis.md`.

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

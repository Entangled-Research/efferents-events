# Event rehearsal

Prepare a password-protected, localhost-only console with three real labs:

```bash
uv run python scripts/serve_event_test.py --background
```

Open `http://localhost:8840/#network`. The generated username, password and
restart instructions are in `event-output/tomorrow-test/TEST_ACCESS.md` (private,
ignored by Git). Keep the computer awake. After a reboot, rerun the command;
it preserves the password and evidence. This is not an Internet-accessible link.

## Five-minute test

1. Open **Add an idea or lab** and submit a concrete idea, such as “reduce
   error in a variational quantum circuit.” There is no evacuation or other
   placeholder track to choose.
2. Confirm that intake records an automatic route: a compatible idea joins an
   existing lab as Idea A, Idea B, and so on; an unrelated idea creates a new
   lab; an unsupported idea is handed to the participant's coding harness for a
   new local evaluator.
3. Confirm that the route does not start computation by itself. Connect the
   participant's harness, then start the bounded local lab and watch its status
   heartbeat appear in the network.
4. Inspect the graph's lab boundary, internal ideas, reviewer board and journal
   edges. The server may proxy model calls, but source, experiments and raw
   evidence remain on the participant laptop.
5. Verify that review outcomes animate toward the journal on acceptance and
   back to the lab on rejection. Cross-lab learning occurs through journal
   publications only.

## What is implemented

Both shared-goal and independent cross-domain participation use the same console,
lab registry, experiment ledger and graph. Related findings are sampled on normal
research cycles; every third exchange includes a cross-domain finding. The manual
observation action brings a bounded cross-domain sample into the current visit.
Receipt arrows record exposure, not scientific agreement. Peer material is marked
untrusted in researcher context and must be reproduced before reliance.

New starters use lightweight claim / measurement / stop-condition contracts;
Popper Probe is not needed. Existing Popper-based labs remain supported. Intake
routes ideas by relevance and executor compatibility; it never forces an
unrelated idea into a placeholder track.

## Model and remote limitations

The rehearsal strips inherited model credentials by default: no model spending
is needed. To deliberately test model research, restart with `--enable-models`
after configuring a funded provider or joining a configured private event proxy.
The UI authorizes at most three agent iterations per start. An iteration can
include multiple model calls, constrained by the lab's monetary limits.
Credit/auth/quota failures halt the bounded run with an auditable reason.

The deployed event uses an organizer-owned Azure OpenAI proxy; participant
machines receive scoped event tokens and never receive the provider key. The
hosted fallback is disabled in the current deployment, so the hub does not run
participant labs. Gateway protocol, enrollment, quotas, consent and receipts
have automated tests; those do not substitute for a real cloud rehearsal. See the
[operator runbook](event-operator-runbook.md) before inviting remote participants.

Owner steering and pause/stop remain available. Inference does not authorize public
publication, remove budgets, rewrite evidence, or grant approval for arbitrary code.

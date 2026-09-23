# Event runbook

This runbook describes the deployed **Docker hub with participant-side labs**.
The alternative systemd/hosted-lab installation is in `EVENT_HOSTING.md`.

## Live services

SSH to the event host, then run from `/opt/efferents-events`:

```bash
docker compose -f deploy/events/compose.yaml ps
docker compose -f deploy/events/compose.yaml logs --tail 100 hub sync
docker compose -f deploy/events/compose.yaml exec hub efferents cluster check /data/cluster
```

Both hub and sync should be healthy/running. Labs execute on participant
machines; there is no hosted keeper and restarting the hub does not restart or
erase a lab. State is in the `efferents-events_events_data` Docker volume.
Provider credentials remain in `deploy/events/.env` (0600), outside Git.

## During the event

Start with the signed-in **Diagnostics** page. Ask the participant to copy that
credential-free report into the support conversation. The report includes the
owner, labs, last heartbeat, sync errors, saved intakes and shared spend. Keep the
existing lab directory and session when applying a fix.

| Situation | Action |
|---|---|
| One lab needs direction or a pause | Use its owner-only steering/pause/resume panel. The daemon applies the durable request on its next heartbeat; inspect the delivery status. |
| Laptop lab is stale | On that laptop, in its existing folder, run `efferents status --submission .`; inspect `lab/daemon.log` and `lab/last_traceback.txt`. Resume with `efferents start --submission . --detach` after repair. Sleeping/offline laptops cannot receive commands until they reconnect. |
| All labs must pause | `docker compose -f deploy/events/compose.yaml exec hub efferents cluster pause-all /data/cluster --reason "operator pause"`. The flag reaches participant daemons on heartbeat. Resume with the corresponding `resume-all` command. |
| Server bug fix | Commit and test; deploy the tracked source and rebuild hub/sync. Refresh the browser. Do not delete the state volume. |
| Participant daemon bug fix | Stop only that daemon, reinstall the verified wheel from its authenticated connection config (`uv pip install --reinstall-package efferents --python .venv/bin/python .event-package/*.whl`), then start from the same submission folder. Its ledger, queues, papers and steering persist. |
| Evals look missing | Diagnostics reports eval sync health. Confirm the current served wheel and `EFFERENTS_OWNER_EVAL_SYNC=1`; reconnect the daemon, then inspect the idea's measurement count and contract. A new unmeasured idea must not inherit another idea's verdict. |
| Proxy budget looks wrong | Inspect shared account diagnostics first. Completed spend and pending holds are separate; heartbeat mirrors are not additional charges. Operator reservation inspection is described below. |
| A participant loses access | Use the returning-user recovery form. Organizer-assisted repair must verify the identity; never post owner tokens in shared chat. |
| Provider request fails | Inspect sanitized daemon/proxy errors and provider status. A timed-out request can retain a budget hold until its billing outcome is known. Do not reset the ledger to make an error disappear. |

For a deployment, keep the previous image and a private state backup. Run
`docker compose -f deploy/events/compose.yaml build` then `up -d --no-build hub sync`.
Verify health, sign-in, the network, one owner control and a participant proxy
request. Never use `down -v`. Caddy and the older gateway are separate services.

After the event, pause participant research, stop local daemons, preserve each
lab folder and back up the Docker volume before changing credentials or removing
infrastructure. Stopping the web hub alone does not stop local CPU experiments.

### Returning participants

The Connect a lab page has a returning-user sign-in form. A valid network token
or owner link restores the current identity in a new browser. New signups receive
a recovery key, shown once; existing participants can create one while signed in.
Save it in a password manager. Only its SHA-256 hash is stored on the hub.

A recovery key works after the 48-hour token window and renews the same token for
48 hours. It preserves the owner ID, original join date, labs and budget ledgers,
so running labs need no token replacement. Replacing a recovery key invalidates
the previous key. Signing out removes only the browser cookie. Recovery and key
replacement write audit events without credentials. Invalid owner links now show
a recovery prompt. A name or event code alone does not recover an account.

Email recovery is not configured. Do not collect unverified email addresses as
proof of identity or claim that email-based signup abuse prevention is active.
Join-code gating and rate limits remain in force; returning users must not create
extra identities to reset budgets. Lost-key cases require organizer-assisted
identity verification before issuing a replacement recovery key.


### Event-day diagnostics and safe account consolidation

Signed-in participants can open **Diagnostics** in the event header and copy a
credential-free report of their labs, last heartbeat, pause reason, intake
sessions and shared account spend. The same report is available at
`GET /api/diagnostics`. Reading it changes no lab state. Keep the original lab
folder when fixing a bug: updating the hub and refreshing the page preserves
intakes, runs, campaigns, papers and pending steering.

The event allocation is per participant across every lab and browser intake.
`proxy.cap_per_owner_usd` is that shared allocation (set it to **50** for the
event); intake and event-wide caps remain additional safeguards. Lab spend is an
absolute expense for comparison, never an independent allocation. Remote
heartbeat spend mirrors proxy charges and is not charged twice. Merged accounts
retain their historical ledger directories, all counted toward the same cap.

Owners can steer, pause and resume a connected remote lab from its lab panel.
The hub durably queues the request; the participant daemon records it verbatim
in its existing charter and steering ledger on the next heartbeat. A later
heartbeat acknowledges delivery. Repeated delivery is idempotent. A stopped or
offline laptop must reconnect before a queued instruction arrives; the hub never
pretends to start a laptop process. Updated daemons are required for this command
protocol. Restart a daemon from its existing submission folder after upgrading;
never create a replacement lab to apply a fix.

Set a random `EFFERENTS_ADMIN_TOKEN` in the hub's server environment to enable
operator-only `GET /api/admin/diagnostics` and `POST /api/admin/accounts/merge`.
Authenticate with `Authorization: Bearer <admin token>`; never put this token in
a participant `.env`, browser URL, screenshot or copied diagnostic report. The
merge body is `{"target_id":"destination owner id","source_ids":["verified duplicate id"],"reason":"identity verification and operator reason"}`.
Only merge organizer-verified identities. The operation renews the destination
session, preserves old lab tokens as aliases, reassigns existing hosted/remote
lab metadata, preserves intake sessions and spend, and writes an audit event.
The operation is idempotent; source accounts remain archived as identity aliases.
Use this live API instead of editing `owners.json` while the server is running.


Budget reservations are written to `budget-reservations.json` before a model
request leaves the hub. Confirmed responses settle and release the hold;
transport failures or a process restart retain uncertain holds conservatively.
Diagnostics shows `reserved_usd` separately from completed `spent_usd`, and both
reduce remaining allocation. Operators can inspect all holds at authenticated
`GET /api/admin/budget/reservations`; they do not expire automatically. Check
provider request/billing records before an operator releases a hold. Completed
ledger records carry the reservation ID for reconciliation. A hold is not a
claim that the provider actually charged its full estimate.

### Correcting verified cached-input charges

Chat Completions reports cached input under `prompt_tokens_details.cached_tokens`;
Responses uses `input_tokens_details.cached_tokens`. Both are subtracted from total
input before applying the cached rate. Never infer historical cache hits from a
repeated prompt. Retain the participant usage ledger as a private, hashed archive.

Operator reconciliation uses `python -m efferents.cluster.billing CLUSTER_ROOT MANIFEST`;
add `--apply` only after the default preview validates every proof. A version-1 JSON
manifest contains `credits`, each with `owner_id`, `original_sha256`, `usage_record`,
and `evidence` (`source`, relative `archive`, `file_sha256`, `record_sha256`, one-based
`line`). The archive must contain the exact usage row. Exact model/token counts,
compatible historical prices, a unique call within five seconds, and matching
owner/event-wide charges are required. Keep the manifest and archives private.

Corrections append negative `billing_adjustment` rows to the original owner and
shared proxy ledgers, retaining all original charges and evidence. Each credit has
an idempotent `proxy-cache-v1:` adjustment ID, both original row hashes, the verified
cached count, corrected cost, and proof hashes. Merged identities include their
original ledgers, so the shared owner and event totals both reflect the credit.
Interrupted corrections can rerun without duplicate credit; incomplete or malformed
ledger tails require inspection before retry. Unknown historical usage is not
credited, and pending reservations remain held until separately reconciled.

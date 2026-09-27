# Separate state for every event

Closing an event must remove sponsored model access, not just hide the network.
Keep the repository; give each event a new Compose project, volume, enrollment
code, admin secret and event-specific provider credential. Never reuse an old
state volume or restore a historical backup into a public event.

## Prepare the next event

From the repository on the deployment host (with `uv sync` completed):

```bash
uv run python deploy/events/prepare.py /srv/events/2026-10-research \
  --name 'October research night' --public-url https://event.example.org
export EFFERENTS_EVENT_PROJECT=efferents-events-2026-10
export EFFERENTS_EVENT_ENV=/srv/events/2026-10-research/hub.env
```

The destination must not already exist. Preparation generates new enrollment and
admin secrets, empty research state, participant-side execution, conservative
rehearsal budgets and all three pause/freeze flags. Secrets are not printed.
Edit `cluster/cluster.yaml` for the URL, tested install revision, models and
budgets. Configure `hub.env` with a fresh, event-specific provider credential
and endpoints. Keep the directory private and outside Git.

Build, create a **new** volume, and seed it once:

```bash
docker compose -f deploy/events/compose.yaml build
# Check the proposed name is unused. Stop here if this succeeds:
docker volume inspect "${EFFERENTS_EVENT_PROJECT}_events_data"
# Only after confirming it does not exist:
docker volume create "${EFFERENTS_EVENT_PROJECT}_events_data"
docker run --rm --user 0 \
  -v "${EFFERENTS_EVENT_PROJECT}_events_data:/data" \
  -v /srv/events/2026-10-research/cluster:/seed:ro \
  --entrypoint sh efferents-events:local \
  -c 'test ! -e /data/cluster && cp -a /seed /data/cluster && chown -R 10001:10001 /data'
docker compose -f deploy/events/compose.yaml up -d --no-build
```

Install the external Popper Probe checkout at `/data/popper-probe` as described
in the hosting guide; it is not copied from old participant state. Validate with
`docker compose -f deploy/events/compose.yaml exec hub efferents cluster check /data/cluster`.
The hub remains bound to loopback port 8810. Only one event on that port may run
at a time. Configure Caddy's event hostname to proxy there when ready to rehearse.

Review the budgets before `efferents cluster resume-all /data/cluster` inside the
hub. For this newly created empty event, also clear `controls/stop_starts` using
`clear_control_flag` from `efferents.cluster.config`. Rehearse a new signup,
intake, local lab, charged proxy request, ownership check, journal sync and pause.
Keep these project/environment exports in your private operator shell setup;
use the same values for every Compose command for that event.

## Retire an event

1. Record a reason with `cluster pause-all`, then `cluster stop-all`. Stop any
   organizer-local daemons. Offline participant CPU processes cannot be killed
   remotely; preserve that limitation in the closure note.
2. Run Compose `down` **without `-v`**. This removes containers and their stored
   provider environments while retaining the evidence volume.
3. Make a private, mode-0600 backup of the volume. Backups can contain historical
   credentials, participant data and recovery hashes; never publish them.
4. With the hub stopped, invalidate **every** owner token and recovery hash,
   including merged aliases, and replace the enrollment code. Preserve owner
   IDs, lab associations, evidence, ledgers and uncertain budget reservations.
   Retain `frozen`, `pause_all` and `stop_starts`; append a closure audit event.
5. Remove the event's active `hub.env`/legacy `.env` and the cluster `.env`.
   Revoke an event-specific provider key at its issuer. If a key is shared,
   remove this event's access without disabling unrelated projects; record that
   issuer revocation was not performed. Removing a file alone does not clear a
   running container's environment, hence step 2.
6. Replace the event Caddy reverse proxy with a `respond "Event closed" 410`
   handler. Validate Caddy before applying it. Check both `/` and a POST to
   `/proxy/openai/v1/responses` return 410, no event containers remain, and port
   8810 has no listener. Preserve unrelated gateway services.

Compose requires its credential file, so an ordinary restart after removal
fails. Do not re-create that file for a retired volume. Store closure notes and
backups privately; use the fresh-event procedure above next time.

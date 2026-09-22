# Hosting an efferents event: one server, many participants

This guide walks a first-time operator through hosting a cluster where up to
about fifty people each own an autonomous lab for a few hours: they join with
a code, sharpen a claim in a popper-probe dialogue in the browser, bind it to
an executor track, and watch their lab run and interact with the others on the
network map. Everything runs on one Linux host that you rent for the day.

## The pieces, in plain terms

- **Droplet (or any VM).** A rented Linux computer in a data centre with a
  public IP address. You log in over SSH the same way you open a terminal
  locally. You pay while it exists; destroy it after the event.
- **DNS A record.** One line at your domain registrar: `event.yourdomain.org`
  points at the droplet's IP. Browsers need a name to issue a certificate.
- **TLS / HTTPS.** The padlock. Participants send their hypothesis text and a
  session cookie; both should be encrypted. Let's Encrypt issues the
  certificate for free and the proxy renews it.
- **Reverse proxy (Caddy).** A small program on ports 80/443 that terminates
  TLS and forwards each request to the efferents server listening privately
  on `127.0.0.1:8800`. The Python server never faces the internet directly.
  nginx does the same job with one more tool (certbot) for TLS; a config is
  in `deploy/nginx.conf.example` if you prefer it.
- **ufw.** Ubuntu's firewall. Only 22 (SSH), 80 and 443 are open.
- **systemd.** Keeps each program running, restarts it if it dies, starts it
  at boot. Four commands cover daily use: `systemctl status <unit>`,
  `systemctl restart <unit>`, `systemctl stop <unit>`, `journalctl -u <unit> -f`.
- **Non-root user.** Everything efferents does runs as the `efferents` user;
  root only installs packages and edits `/etc`.

## Two ways in

- **Terminal path (the real efferents flow).** A participant joins in the
  browser, copies one instruction into their own coding agent, and the agent
  reads `https://<host>/intake.md`: installs efferents on their laptop, runs
  the popper dialogue in the terminal, downloads a track from the hub, maps
  the falsifier, and starts a local daemon. Experiments run on their laptop.
  The daemon's model calls go through the hub's proxy with the organizer's
  key (`EFFERENTS_API_BASE=https://<host>/proxy/openai/v1`, the participant's
  network token as the key), so no provider key ever leaves the server and
  each participant has a proxy cap. The daemon registers with the hub, sends
  a heartbeat every 30 s, pushes accepted papers, and pulls the shared feed
  and the reviews other labs wrote about it. The hub can pause it.
- **Hosted fallback.** "New lab" in the browser runs the dialogue and the lab
  on the server for anyone whose laptop setup fails.

Both kinds of lab appear on the same network map and shared journal.

## What runs on the host

| Process | Unit | Job |
|---|---|---|
| Web server | `efferents-cluster` | Join, intake dialogue, track binding, lab creation, lab-scoped API, network view |
| Keeper | `efferents-keeper` | Restarts crashed daemons, enforces the cluster spend cap, writes `status.json`, rotates logs |
| Sync | `efferents-sync` | Publishes every lab's journal into the shared hub, fans it out, runs cross-lab reviews |
| Backup | `efferents-backup.timer` | Tarball of the cluster directory every 15 minutes |
| Hosted lab daemons | (spawned) | One `efferents start --detach` per fallback lab; terminal-path labs run on laptops |

All three services use `KillMode=process`, so restarting any of them leaves
the lab daemons running.

## Caps, in one place

| Cap | Where | Covers |
|---|---|---|
| `proxy.cap_per_owner_usd` / `proxy.cap_total_usd` | `cluster.yaml` | Model calls from participants' laptops through the hub |
| `labs.total_cap_usd` | `cluster.yaml`, written into each lab.yaml | A lab's own ledger (hosted labs enforce it locally; laptop labs too) |
| `intake.*` | `cluster.yaml` | Browser dialogue and falsifier binding |
| `caps.reviews_total_usd` | `cluster.yaml` | Cross-lab reviews |
| `caps.cluster_total_usd` | `cluster.yaml` | Sum of all of the above; the keeper freezes the cluster here and asks every lab, laptop or hosted, to pause |
| Azure spending alert/budget | Azure Cost Management | An alerting backstop; it is not an instant hard stop |

## Sizing

Fifty daemons idle most of the time waiting on model replies; the experiment
tracks run on the host's CPUs. For seconds-scale runs start with **Ubuntu
24.04, 8 vCPU / 16 GB RAM**; for minutes-scale runs use **16 vCPU / 32 GB**
on event day. Between now and the event a **1 vCPU / 2 GB ($12/month)**
droplet is enough for testing with a handful of people; resize it in place
the evening before (a few minutes of downtime, disk and DNS unchanged) and
back down afterwards. Hourly billing is capped at the monthly price. Measure daemon memory during the
rehearsal (`efferents cluster status` prints `daemon_rss_gb`); if fifty
daemons exceed about 60 % of RAM, resize to 32 GB the day before. Take a
snapshot of the droplet the evening before the event.

## Setup, step by step

1. Create the droplet, add your SSH key, point the DNS A record at it. No
   domain yet? Use `DOMAIN=<droplet-ip>.sslip.io` (a free wildcard DNS
   service that resolves any `a.b.c.d.sslip.io` to that IP); Let's Encrypt
   issues certificates for it and you can switch to a real domain later.
2. Copy this repository's `deploy/` directory to the host and run:

   ```bash
   sudo DOMAIN=event.yourdomain.org bash deploy/setup.sh          # main
   sudo REF=glasgow DOMAIN=event.yourdomain.org bash deploy/setup.sh   # an event branch
   ```

   It installs packages and Caddy, creates the `efferents` user, opens the
   firewall, installs `uv`, checks out a release under
   `/srv/efferents/releases/<sha>` with its own virtualenv, clones
   popper-probe, initialises `/srv/efferents/cluster`, and installs the
   systemd units and the Caddyfile.
3. In Azure AI Foundry, create an Azure OpenAI resource and three Global
   Standard deployments named exactly `gpt-4.1-nano`, `gpt-5.6-luna`, and
   `gpt-5.6-sol`. Availability and quota depend on region and subscription.
   Put the resource's `https://...openai.azure.com/openai/v1` endpoint in
   both `EFFERENTS_AZURE_OPENAI_ENDPOINT` and `EFFERENTS_API_BASE`, and its
   key in `OPENAI_API_KEY` in `/etc/efferents/event.env` (mode 0600). Never
   paste the key into the browser, a track, or participant instructions.
   Set an Azure Cost Management budget and alerts as an independent warning.
4. Edit `/srv/efferents/cluster/cluster.yaml`: the event name, the join code
   you will put on a slide, per-lab and cluster caps, cadence. Set
   `network.install_ref` to the same tested commit or event branch used by
   the host; otherwise terminal participants may install an older `main`.
5. Add only real, event-approved tracks under
   `/srv/efferents/cluster/tracks/<id>/` (contract below). An empty catalogue is
   valid: unrelated ideas are handed to the participant's coding harness to
   build a new local executor.
6. Validate and start:

   ```bash
   sudo bash -c 'set -a; . /etc/efferents/event.env; exec runuser -u efferents -- /srv/efferents/current/.venv/bin/efferents cluster check /srv/efferents/cluster'
   sudo systemctl start efferents-cluster efferents-keeper efferents-sync efferents-backup.timer
   ```

7. Open `https://event.yourdomain.org/`, join with the code, run one intake,
   create a lab, watch it run. Before opening the room, confirm all three
   Azure deployments answer a small request, the proxy ledger increments,
   a second join token cannot use the first owner's lab, and pause/stop
   controls work. Do not start the public event on an untested model key.

## Track contract (what the owner authors)

A track is an executor template a participant's hypothesis binds to:

```
tracks/<id>/
  track.yaml            title, summary, domain, knobs[], columns[], bucket_axes, example_falsifiers
  submission/           a complete submission minus hypothesis.md:
    README.md  lab.yaml  src/  configs/  (context/ optional)
```

`lab.yaml` must validate on its own (source dir, run command with
`{config_path}`, config template, headline metric), must not predefine
`falsifiers`, and should set `executor.env_passthrough: [OMP_NUM_THREADS]`
with `run_timeout_s` a little above the slowest expected run (runs of a few
minutes on CPU are fine; set 600–900 s). Fifty labs run their experiments
concurrently on the host, so a run that takes 2 minutes alone takes longer
when 50 share 8 cores: for minutes-scale tracks use a 16 vCPU droplet on
event day and expect roughly 15–25 runs per lab in three hours. `columns[]` lists every ledger column the
runner emits, in participant-readable words; the falsifier mapper may only
use those. `efferents cluster check` validates every track and fails fast.

## Cost and rate limits

This branch routes routine research and literature review to Luna, difficult
analysis and supervision to Sol, and short rebuttals to GPT-4.1 nano. Autonomous
code editing stays disabled by the event intake policy; Sol is configured for
the Coder only if an operator separately permits that capability. The proxy
accepts only these three deployments, text/function-tool Chat Completions,
non-streaming calls, at most 8,192 output tokens and 200 kB of request body.
Its ledger uses conservative short-context Global Standard prices; check the
current price and deployment type in Azure before setting the event budget.
Do not reuse older Sonnet-based cost projections for this lineup.

The shipped `cluster.yaml` defaults are **rehearsal values**: cluster cap $20,
$10 per lab, $10 of laptop proxy use per owner, and $1 of intake per person.
Raise the cluster cap for a multi-lab event; set an Azure budget alert below
your available credit and check actual usage in
Azure Cost Management during rehearsal. Azure budgets alert; the event's own
caps are the active stop mechanism.

Check Azure quotas for each of the three deployments. The cluster limits
in-flight calls across all daemons (`EFFERENTS_MAX_CONCURRENT_CALLS=12`), but
does not create extra Azure quota or automatically switch providers on 429s.
Rehearse at the intended attendance, inspect 429s and latency, and request
quota increases before event day if needed.

## Keys and privacy

Keys live only in `/etc/efferents/event.env`. The server and daemons read
them from the environment; experiment commands get an allowlisted
environment without them; participants never see them. Cookies are
`HttpOnly; SameSite=Lax; Secure`. Anyone who joined can view every lab; only
the owner link can steer, pause, resume or stop a lab. Every steering act is
recorded verbatim in the lab's charter and steering ledger with the
participant's name.

## Updating code during the event

Never `git pull` in place: running daemons import lazily and would load new
code mid-flight. Check out a new release directory, sync its venv, run the
tests there, flip the `current` symlink, and restart only the services:

```bash
sudo -u efferents bash -c '
  set -e; cd /srv/efferents
  git clone --depth 1 --branch <event branch> https://github.com/Entangled-Research/efferents-events releases/new && (cd releases/new && uv sync && uv run pytest -m "not integration and not slow" -q)
  sha=$(git -C releases/new rev-parse --short HEAD); mv releases/new releases/$sha
  ln -sfn releases/$sha current.new && mv -T current.new current'
sudo systemctl restart efferents-cluster efferents-keeper efferents-sync
```

Daemons keep running from the release they were started in. Restart them
(`efferents cluster restart-all --stagger 3`) only if daemon-side code changed.
The hosted web server picks up the new release after its service restart;
refresh the browser normally. Persistent tracks are never overwritten by a
release update. To change an installed track, review and update that directory
separately, then run `efferents cluster check` before restarting the web service.

## Rehearsing from a laptop

For a small rehearsal you can run `efferents serve --cluster <dir>` on a Mac
and expose it with `cloudflared tunnel --url http://127.0.0.1:8800`. Do not
run the event that way: the URL changes each run, the laptop sleeps, there is
no restart-on-crash, and fifty daemons will starve a laptop.

## Load test

`scripts/event_loadtest.py` clones a track into N labs, joins as N owners,
starts them in dry-run (no model calls) or cheap mode, polls the API from N
simulated browsers, and reports latency, liveness, memory and spend against
go/no-go thresholds. Run it at 50 in dry-run a week before and at 5 in cheap
mode; run the full rehearsal with the real tracks the day before.

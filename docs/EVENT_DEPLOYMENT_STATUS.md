# Events deployment

The Events repository includes the framework network and the September 23 event
readiness fixes, preserving participant identity, owner-only control, intake,
the model proxy and remote-lab transport. The production deployment is independent of the
older framework dashboard.

- Droplet: `161.35.164.202`, existing DigitalOcean LON1 Ubuntu host on the
  Basic 2 vCPU / 2 GB plan (storage kept at 50 GB so it can be downsized), with
  a 4 GB swap file. Nothing runs on it but the hub, the legacy gateway and Caddy.
- Events source: `/opt/efferents-events`.
- Compose: `deploy/events/compose.yaml`; loopback port **8810**.
- State: Docker volume `efferents-events_events_data`, under `/data/cluster`.
- URL: <https://events.161-35-164-202.sslip.io>.
- Existing framework dashboard on 8800 and its private hostname are preserved.

## Operating state

As of 2026-09-23, **intake and participant API testing are enabled**. The owner
authorized clearing the initial freeze; automatic hosted lab starts remain off.
The owner decided on 2026-09-22 that nothing runs on the droplet:
`labs.hosted: false` is set in `/data/cluster/cluster.yaml`, so the hub never
creates a lab on the host and every lab runs on a participant's laptop or web
harness.
Azure credentials and the Azure OpenAI v1 endpoint are configured in
`deploy/events/.env` (0600), outside Git. Both `EFFERENTS_API_BASE` (host calls)
and `EFFERENTS_AZURE_OPENAI_ENDPOINT` (participant proxy) point to Azure.
Participant machines receive their own network token, never the provider key.

Azure Global Standard deployments are available for `gpt-5.6-luna`,
`gpt-5.6-sol` and `gpt-4.1-nano`; small real requests passed for all three.
The current participant connection config overrides all agent roles to
`openai/gpt-5.6-sol` through `network.lab_model`. Treat that authenticated config
as authoritative for participant cost and model selection; role-specific
Luna/nano defaults do not describe this live override. Intake and the participant
proxy have both returned real model responses over HTTPS.

The external Popper checkout is installed at `/data/popper-probe`. The old
evacuation placeholder has been removed from the event catalogue; an empty
hosted-track catalogue is valid because new executors are built on participant
laptops. `efferents cluster check /data/cluster` passes.
Configured safeguards: $1,500 for the cluster and $1,500 proxy total; **$50 per
person shared across intake and every lab**, including merged identity aliases.
Lab spend is an absolute expense, not another allocation. A lab may set a lower
local safety cap. Intake retains its additional $50 event/$1 person safeguards;
reviews have a $3 cap. Remote heartbeat expenses mirror proxy charges and are
not charged twice. In-flight model holds persist through hub restarts. These
limits are separate from Azure credits.
The join code is retained in private access notes outside the repository.

Local testing uses `http://localhost:8843`; the legacy preview at port 8840
retains its Basic login. Local daemon credentials are in
`~/.efferents-events-local/.env` (0600). Restart the preview process after changing
that file. Recreate the Docker hub after changing its Compose environment file.

The live stack runs **hub and sync**, with sync configured `--no-reviews`.
Research and the three-reviewer board execute in each participant lab; accepted
manuscripts then enter the shared journal. The hosted-lab keeper is intentionally
absent because `labs.hosted: false`. The hub's proxy enforces the shared account
and proxy caps; this deployment does not claim keeper enforcement for arbitrary
non-proxy local spending.

The September 23 rehearsal uses a separate ChemistryNerd owner and a chemistry
lab with three ideas, real ORD data, paired local trials and Azure-backed agents.
The chemistry question is scoped to reaction-family evidence retrieval: ORD
family annotations are not elementary-mechanism ground truth. Preserve negative
results and report dataset coverage alongside metrics.

The deployed application revision is recorded on the host in
`deployed-event-ready-20260923.json`; the matching served wheel is authenticated
and SHA-256 pinned by `GET /api/network/config`. The readiness baseline passed
873 tests locally (3 skipped, 1 deselected). Follow-up protocol-specific tests
and live checks are documented in the private rehearsal report.

Signed-in owners have **Diagnostics**, shared-budget reporting, recoverable
sessions and durable remote steer/pause/resume commands. Operator diagnostics,
identity merges and reservation inspection require the server-only admin token.
Do not copy that token into participant credentials or support reports.

## Update and rollback

Build with `docker compose -f deploy/events/compose.yaml build`, then use `up -d`.
The image uses tracked code and versioned starter inputs only. State and `.env`
survive updates. Keep the previous image tag for rollback; never use `down -v`.
The repository CI deploy job targets this Events stack after tests pass, but is
disabled until the `DIGITALOCEAN_DEPLOY_ENABLED` variable and production SSH
secrets are configured. Manual deployment does not imply automatic deployment.

Caddy is shared with the existing gateway. Its Events hostname proxies 8810;
the original hostname continues to proxy 8800. Back up and validate the Caddy
configuration before changing it. Do not run `deploy/setup.sh` over this Docker
host: that script describes the alternative systemd installation.

# Events deployment

The Events repository includes the framework network through upstream commit
`89ed429`, preserving participant identity, owner-only control, intake, the model
proxy and remote-lab transport. The production deployment is independent of the
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

As of 2026-09-22, **intake and participant API testing are enabled**. The owner
authorized clearing the initial freeze; automatic hosted lab starts remain off.
The owner decided on 2026-09-22 that nothing runs on the droplet:
`labs.hosted: false` is set in `/data/cluster/cluster.yaml`, so the hub never
creates a lab on the host and every lab runs on a participant's laptop or web
harness.
Azure credentials and the Azure OpenAI v1 endpoint are configured in
`deploy/events/.env` (0600), outside Git. Both `EFFERENTS_API_BASE` (host calls)
and `EFFERENTS_AZURE_OPENAI_ENDPOINT` (participant proxy) point to Azure.
Participant machines receive their own network token, never the provider key.

Azure Global Standard deployments match the configured names: `gpt-5.6-luna`
for intake/librarian/review, `gpt-5.6-sol` for supervisor/analyst/coder, and
`gpt-4.1-nano` for rebuttal. Small real requests passed for all three. A browser
intake API conversation passed on the HTTPS hub and local preview; the remote
participant proxy also returned a real model response. Verification intakes
were abandoned after testing and did not create labs.

The external Popper checkout is installed at `/data/popper-probe`. The old
evacuation placeholder has been removed from the event catalogue; an empty
hosted-track catalogue is valid because new executors are built on participant
laptops. `efferents cluster check /data/cluster` passes.
Configured caps (set 2026-09-22 for the event): $20 for the cluster and $20
proxy total; $10 per person through the proxy and $10 per lab, so one person
can spend their allowance on one lab or spread it across two; $5 intake total
($1 per person); $3 reviews. These are separate from Azure credits.
The join code is retained in private access notes outside the repository.

Local testing uses `http://localhost:8843`; the legacy preview at port 8840
retains its Basic login. Local daemon credentials are in
`~/.efferents-events-local/.env` (0600). Restart the preview process after changing
that file. Recreate the Docker hub after changing its Compose environment file.

This is not yet a fully rehearsed live research event. Follow `EVENT_HOSTING.md`
and `EVENT_RUNBOOK.md` to enable keeper and journal-sync services and rehearse a
complete owned lab with real review output. Only the web hub currently runs;
the keeper's aggregate-cap enforcement and continuous hosted-lab supervision
are not active. Intake and proxy retain their own configured caps. Enable
automatic hosted lab starts only when that operational setup is ready.

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

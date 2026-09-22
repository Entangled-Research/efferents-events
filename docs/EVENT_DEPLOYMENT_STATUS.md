# Events deployment

The Events repository includes the framework network through upstream commit
`89ed429`, preserving participant identity, owner-only control, intake, the model
proxy and remote-lab transport. The production deployment is independent of the
older framework dashboard.

- Droplet: `161.35.164.202`, existing DigitalOcean LON1 Ubuntu host.
- Events source: `/opt/efferents-events`.
- Compose: `deploy/events/compose.yaml`; loopback port **8810**.
- State: Docker volume `efferents-events_events_data`, under `/data/cluster`.
- URL: <https://events.161-35-164-202.sslip.io>.
- Existing framework dashboard on 8800 and its private hostname are preserved.

## Operating state

Initial deployment is **frozen**, with automatic lab starts disabled. The join
screen and participant network are available; live research is not enabled.
The external Popper checkout is installed at `/data/popper-probe` and the
evacuation track passes validation. The readiness check reports one problem:
missing model-provider credentials. No provider keys were found on the host. The random join code is stored on the
host at `/root/efferents-events-access.txt` (0600), outside the repository.

Before opening an event, follow `EVENT_HOSTING.md` and `EVENT_RUNBOOK.md`: provision
provider credentials in `deploy/events/.env` (0600), check Azure model/deployment pricing and caps,
run `efferents cluster check /data/cluster`, and rehearse a complete owned lab
with real review output. Only then clear the frozen control flag and explicitly
enable automatic lab starts if desired. Keeper and journal-sync services also
need to be enabled for continuous hosted research; this deployment starts only
the web hub. Do not interpret a healthy HTTP endpoint as a ready research event.

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

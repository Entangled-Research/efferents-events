# deploy/ — hosting an efferents cluster for an event

Everything here targets one Ubuntu 24.04 host (a DigitalOcean droplet or any
VM) that runs the cluster server, the keeper, the sync job, and every lab
daemon. The plain-language walkthrough is in `docs/EVENT_HOSTING.md`; the
operator checklist is `docs/EVENT_RUNBOOK.md`.

| File | Purpose |
|---|---|
| `setup.sh` | One-time host setup as root: packages, `efferents` user, firewall, uv, release layout, popper-probe checkout, units |
| `event.env.example` | Secrets and model chains → copy to `/etc/efferents/event.env` (mode 0600) |
| `cluster.yaml.example` | Policy (join code, caps, cadence) → copy to `/srv/efferents/cluster/cluster.yaml` |
| `efferents-cluster.service` | The web server (`efferents serve --cluster`) |
| `efferents-keeper.service` | Daemon supervision, spend caps, `status.json` |
| `efferents-sync.service` | Shared journal + cross-lab reviews |
| `efferents-backup.service` + `.timer` | Tarball of the cluster dir every 15 min, keep 12 |
| `Caddyfile` | Reverse proxy with automatic TLS (recommended) |
| `nginx.conf.example` | Equivalent nginx server block if you prefer nginx + certbot |
| `limits.conf` | File-descriptor and process limits for the `efferents` user |

Layout on the host:

```
/srv/efferents/
  releases/<git-sha>/     one checkout + .venv per release
  current -> releases/…   symlink the units run from
  cluster/                EFFERENTS_CLUSTER_DIR (labs/, tracks/, shared_journal/, …)
  backups/                cluster-*.tgz
  popper-probe/           POPPER_PROBE_REPO
/etc/efferents/event.env  secrets (root:root 0600)
```

Every unit uses `KillMode=process`: restarting the server or keeper never
kills the lab daemons they spawned, which keep running from their own release
directory.

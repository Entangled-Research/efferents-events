# Event runbook

Operator checklist for a hosted efferents cluster. Commands run on the host
as the `efferents` user with the event environment loaded:

```bash
sudo -u efferents -i
set -a; . /etc/efferents/event.env; set +a
cd /srv/efferents/current
alias ef='.venv/bin/efferents'
C=/srv/efferents/cluster
```

## Watch

- Wall display: the network view in a browser you joined, or
  `watch -n 30 .venv/bin/efferents cluster status $C`.
- Provider console: usage and rate-limit pages.
- Logs: `journalctl -u efferents-cluster -u efferents-keeper -u efferents-sync -f`.
- Phone: subscribe to the `NTFY_TOPIC` from `event.env`.

## Before the doors open

- `systemctl status caddy efferents-cluster efferents-keeper efferents-sync` all active.
- `ef cluster check $C` prints `ok`.
- `ef cluster status $C --refresh` shows free disk above 20 GB and no labs.
- Create one canary lab yourself, watch a run, a digest and the shared
  journal entry appear, then pause it or leave it as the first node.
- Put the join code and the URL on a slide. Remind people to keep their owner
  link.

## Situations

| Situation | Action |
|---|---|
| One lab spends or misbehaves | `ef cluster pause $C --lab-id X --by operator --reason "…"`; the daemon idles at its next step. `ef cluster resume $C --lab-id X` to continue. |
| Stop all spending now | `ef cluster pause-all $C` (queues an owner pause on every lab and sets `controls/pause_all`, which also stops keeper restarts). `ef cluster resume-all $C` lifts it and clears `frozen`. |
| A lab crashed | The keeper restarts it within a tick, at most 3 times in 30 minutes, then quarantines it (`controls/halt_<id>`). Read `labs/<id>/lab/daemon.log` and `lab/last_traceback.txt`; fix; `rm $C/controls/halt_<id>`. |
| A lab hit its cap and deserves more | `ef cluster raise-cap $C --lab-id X --total 18` (edits lab.yaml, restarts the daemon). |
| Cluster cap approaching or reached | Everything pauses at the cap (`controls/frozen`). Raise `caps.cluster_total_usd` in `cluster.yaml`, check the provider workspace limit, then `ef cluster resume-all $C`. |
| 429s or "rate limited" notebook lines | Lower `EFFERENTS_MAX_CONCURRENT_CALLS` in `event.env`, `systemctl restart efferents-cluster efferents-keeper`, then `ef cluster restart-all $C --stagger 3` (daemons read the limit at start). Or raise `EFFERENTS_CADENCE_RESEARCHER_MIN_INTERVAL_S`. |
| Provider outage | Labs halt and re-probe with backoff (cap 5 min). If prolonged, set `EFFERENTS_MODEL=openai/gpt-4.1` in `event.env` and `restart-all`. |
| Key compromised | New key in the console → edit `event.env` → `systemctl restart efferents-cluster efferents-sync` → `ef cluster restart-all $C --stagger 3` → revoke the old key. |
| Server bug fix | New release directory procedure in `docs/EVENT_HOSTING.md`; daemons keep running. |
| Disk filling | `du -sh $C/labs/* | sort -h`; the keeper rotates daemon logs and blocks new starts below `min_free_disk_gb`; delete old `backups/*.tgz`. |
| Host out of memory | `ef cluster pause-all $C`, `ef cluster stop-all $C`, resize the droplet, `ef cluster start-all $C --stagger 3`. Labs resume from `lab/` state. |
| Participant lost their owner link | Their token is in `$C/owners.json` (server-only); read it and hand them `https://<host>/?owner=<token>` privately. |

## After

1. `ef cluster stop-all $C`.
2. Final backup: `systemctl start efferents-backup.service`; download
   `/srv/efferents/backups/` and the DigitalOcean snapshot.
3. Revoke every key in the provider console.
4. Give each participant their lab directory (`labs/<id>`): hypothesis,
   charter, run ledger, papers, and the reviews other labs wrote about them.
5. Destroy the droplet, or at least `ufw deny 80,443/tcp`.

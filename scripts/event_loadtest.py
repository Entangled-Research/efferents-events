#!/usr/bin/env python3
"""Load test and rehearsal for a hosted efferents cluster.

Clones one track into N labs (each with a gated hypothesis), joins as N fake
owners over HTTP, starts the daemons (dry-run by default: no model calls),
polls the read endpoints from N simulated browsers, samples host load and
per-daemon memory, and reports latency, liveness, sync fan-out and spend
against go/no-go thresholds.

    uv run python scripts/event_loadtest.py --cluster-dir /srv/efferents/cluster \
        --base-url http://127.0.0.1:8800 --n 50 --track coefficient-sweep \
        --duration 900 --clients 50 --poll 4 --report loadtest.json [--teardown]

Requires the cluster server to be running at --base-url with the cluster's
join code. Labs are named loadtest-NN; --teardown stops and removes them.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from efferents.cluster.config import activate_environment, daemon_env, load_cluster_config  # noqa: E402
from efferents.cluster.labs import create_lab  # noqa: E402
from efferents.cluster.owners import OwnerStore  # noqa: E402
from efferents.cluster.tracks import load_tracks  # noqa: E402
from efferents.registry import Registry  # noqa: E402

HYP = """\
---
slug: loadtest-{n}
created: 2026-01-01
status: active
falsifiability_gate: passed
literature_pass: none
---

## Original framing

Load-test lab {n}: a bigger coefficient lowers the loss.

## Operational restatement

Runs with coefficient >= 0.7 report synthetic_loss < 0.1 on 4 of 5 seeds.

## Falsifier(s)

Median synthetic_loss over >= 4 runs at coefficient >= 0.7 is >= 0.1.

## Test design

Sweep coefficient over 0.7, 0.8, 0.9 with 5 seeds each.

## Auxiliary assumptions

The stub optimum is fixed.

## Distinctiveness

Threshold claim, not a slope claim.

## References

## Intake log

- synthetic load-test hypothesis
"""


class Http:
    def __init__(self, base_url: str):
        parts = urlsplit(base_url)
        self.host = parts.hostname or "127.0.0.1"
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.https = parts.scheme == "https"

    def request(self, method: str, path: str, *, body=None, headers=None):
        conn_cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        conn = conn_cls(self.host, self.port, timeout=30)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        t0 = time.monotonic()
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        elapsed = time.monotonic() - t0
        set_cookie = resp.getheader("Set-Cookie", "")
        conn.close()
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}
        return resp.status, payload, set_cookie, elapsed


def join(http_: Http, code: str, name: str) -> dict:
    status, body, set_cookie, _ = http_.request("POST", "/api/join", body={"code": code, "name": name})
    if status != 200:
        raise SystemExit(f"join failed for {name}: {status} {body}")
    cookie = set_cookie.split(";", 1)[0]
    return {"Cookie": cookie, "X-Efferents-CSRF": body["csrf_token"], "owner_id": body["owner"]["id"]}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = min(len(values) - 1, int(round((len(values) - 1) * p)))
    return values[k]


def rss_gb(pids: list[int]) -> float:
    total = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
        except OSError:
            continue
    return total / 1024 / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cluster-dir", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8800")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--track", default=None, help="track id (default: first track)")
    ap.add_argument("--mode", choices=("dry-run", "cheap"), default="dry-run")
    ap.add_argument("--cheap-labs", type=int, default=5, help="labs that use the real model in cheap mode")
    ap.add_argument("--duration", type=int, default=600)
    ap.add_argument("--clients", type=int, default=50)
    ap.add_argument("--poll", type=float, default=4.0)
    ap.add_argument("--stagger", type=float, default=1.0)
    ap.add_argument("--report", default="loadtest.json")
    ap.add_argument("--teardown", action="store_true")
    ap.add_argument("--no-start", action="store_true", help="create labs and poll without starting daemons")
    args = ap.parse_args()

    cfg = load_cluster_config(args.cluster_dir)
    activate_environment(cfg)
    tracks = load_tracks(cfg.tracks_path)
    track = tracks[args.track] if args.track else next(iter(tracks.values()))
    http_ = Http(args.base_url)
    owners = OwnerStore(cfg.paths.owners, max_age_hours=cfg.session.max_age_hours)

    # --- create labs -----------------------------------------------------------
    labs = []
    for i in range(1, args.n + 1):
        name = f"loadtest-{i:02d}"
        existing = Registry().get(name)
        owner = owners.by_id(owners.owner_of(name).owner_id) if owners.owner_of(name) else None
        if owner is None:
            headers = join(http_, cfg.join_code, f"Load Tester {i:02d}")
            owner = owners.by_id(headers["owner_id"])
        else:
            headers = {"Cookie": f"efferents_owner={owner.token}"}
            _, control, _, _ = http_.request("GET", "/api/control", headers=headers)
            headers["X-Efferents-CSRF"] = control.get("csrf_token", "")
        if existing is None:
            create_lab(cfg, track=track, owner=owner, hypothesis_text=HYP.format(n=i),
                       first_claim=f"load test {i}", lab_id=name, falsifiers=None,
                       design_notes="- load test", session_id=None)
            owners.add_lab(owner.owner_id, name)
        labs.append({"lab_id": name, "headers": headers, "dry_run": True})
    if args.mode == "cheap":
        for lab in labs[: args.cheap_labs]:
            lab["dry_run"] = False
    print(f"{len(labs)} labs ready ({sum(1 for line in labs if not line['dry_run'])} with real model calls)")

    # --- start daemons ---------------------------------------------------------
    if not args.no_start:
        env = daemon_env(cfg)
        for i, lab in enumerate(labs):
            rec = Registry().get(lab["lab_id"])
            cmd = [sys.executable, "-m", "efferents", "start", "--submission", rec.submission_dir,
                   "--lab-root", rec.lab_root, "--detach"]
            if lab["dry_run"]:
                cmd.append("--dry-run")
            result = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=60)
            if result.returncode:
                print(f"start failed for {lab['lab_id']}: {result.stderr.strip()[-200:]}")
            if i < len(labs) - 1:
                time.sleep(args.stagger)
        print("daemons started")

    # --- poll --------------------------------------------------------------------
    latencies: dict[str, list[float]] = {"labs": [], "state": [], "activity": [], "control": []}
    errors = {"non2xx": 0, "exceptions": 0}
    stop = threading.Event()
    lock = threading.Lock()

    def client(idx: int):
        lab = labs[idx % len(labs)]
        headers = {"Cookie": lab["headers"]["Cookie"]}
        while not stop.is_set():
            for kind, path in (("labs", "/api/labs"),
                               ("state", f"/api/labs/{lab['lab_id']}/state"),
                               ("activity", f"/api/labs/{lab['lab_id']}/activity"),
                               ("control", f"/api/labs/{lab['lab_id']}/control")):
                try:
                    status, _, _, elapsed = http_.request("GET", path, headers=headers)
                    with lock:
                        latencies[kind].append(elapsed)
                        if not 200 <= status < 300:
                            errors["non2xx"] += 1
                except Exception:
                    with lock:
                        errors["exceptions"] += 1
            stop.wait(args.poll)

    threads = [threading.Thread(target=client, args=(i,), daemon=True) for i in range(args.clients)]
    for t in threads:
        t.start()

    samples = []
    started = time.monotonic()
    while time.monotonic() - started < args.duration:
        time.sleep(10)
        status = json.loads(cfg.paths.status.read_text()) if cfg.paths.status.exists() else {}
        by_id = {line["lab_id"]: line for line in status.get("labs", [])}
        pids = [line["pid"] for line in by_id.values() if line.get("pid")]
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = None
        alive = sum(1 for line in labs if by_id.get(line["lab_id"], {}).get("status") in ("running", "paused"))
        samples.append({"t": round(time.monotonic() - started), "alive": alive, "load1": load1,
                        "rss_gb": round(rss_gb(pids), 3),
                        "spend": status.get("totals", {}).get("spend_usd")})
        print(f"t={samples[-1]['t']:>4}s alive={alive}/{len(labs)} load1={load1} "
              f"rss={samples[-1]['rss_gb']} GB spend=${samples[-1]['spend']}", flush=True)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    # --- verdict -----------------------------------------------------------------
    restarts = 0
    if cfg.paths.restarts.exists():
        restarts = sum(1 for line in cfg.paths.restarts.read_text().splitlines()
                       if "\"loadtest-" in line)
    fanout_ok = True
    hub = cfg.paths.shared_journal / "journal.md"
    if hub.exists():
        for lab in labs:
            rec = Registry().get(lab["lab_id"])
            ext = Path(rec.submission_dir) / "paper" / "external_journal.md"
            if not ext.exists():
                fanout_ok = False
    p95 = percentile(latencies["state"], 0.95)
    p99 = percentile(latencies["state"], 0.99)
    last = samples[-1] if samples else {}
    checks = {
        "state_p95_under_500ms": p95 < 0.5,
        "state_p99_under_1500ms": p99 < 1.5,
        "zero_non2xx": errors["non2xx"] == 0,
        "zero_exceptions": errors["exceptions"] == 0,
        "all_daemons_alive": args.no_start or (last.get("alive") == len(labs)),
        "no_unintended_restarts": restarts == 0,
        "sync_fanout": fanout_ok,
    }
    report = {
        "n": len(labs), "mode": args.mode, "duration_s": args.duration, "clients": args.clients,
        "latency_s": {k: {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95),
                          "p99": percentile(v, 0.99), "n": len(v)} for k, v in latencies.items()},
        "errors": errors, "restarts": restarts, "samples": samples, "checks": checks,
        "go": all(checks.values()),
    }
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2))
    print("GO" if report["go"] else "NO-GO")

    if args.teardown:
        for lab in labs:
            subprocess.run([sys.executable, "-m", "efferents", "stop", "--lab-id", lab["lab_id"]],
                           env=daemon_env(cfg), capture_output=True, text=True)
            rec = Registry().get(lab["lab_id"])
            if rec is not None:
                shutil.rmtree(rec.submission_dir, ignore_errors=True)
                Registry().remove(lab["lab_id"])
        print("torn down")
    return 0 if report["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

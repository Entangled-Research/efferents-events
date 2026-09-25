"""Credential-free, owner-scoped event diagnostics; reading never resets state."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from efferents.cluster.budget import coordinator, owner_budget
from efferents.cluster.config import control_flag


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def scrub(value: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    return re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|token|password)\s*[=:]\s*)[^\s,;]+",
                  r"\1[redacted]", value)[:2000]


def diagnostics(context, owner=None) -> dict:
    owners = [owner] if owner else context.owners.all()
    ids = {oid for item in owners for oid in item.identity_ids}
    credentials = [item.token for item in context.owners._owners.values()]
    import os
    credentials.extend(value for key, value in os.environ.items()
                       if any(term in key.upper() for term in ("TOKEN", "KEY", "SECRET", "PASSWORD")))
    labs = []
    for item in context.hub.list_labs():
        reg, beat = item["registration"], item["heartbeat"]
        if reg.get("owner_id") not in ids:
            continue
        lab_id = reg["lab_id"]
        paused = control_flag(context.paths, f"halt_{lab_id}")
        status = context.hub._status(beat)
        error = scrub(str(beat.get("halt_reason") or ""), credentials)
        if not beat.get("runs") and not error:
            error = "No completed experiments reported. Check the existing lab/daemon.log and executor smoke test before interpreting a verdict."
        eval_error = scrub(str(beat.get("eval_sync_error") or ""), credentials)
        snapshot = _read(item["dir"] / "owner-evals.json")
        labs.append({"id": lab_id, "name": reg.get("display_name") or reg.get("name") or lab_id,
                     "execution": "participant", "status": status,
                     "last_seen": beat.get("ts"), "spend_usd": beat.get("spend_usd", 0),
                     "runs": beat.get("runs", 0), "pause_reason": context.hub._message_for(lab_id),
                     "last_error": error or eval_error or None,
                     "eval_sync_error": eval_error or None,
                     "eval_synced_at": snapshot.get("synced_at"),
                     "eval_snapshot_present": bool(snapshot),
                     "recovery_hint": ("Ask the organizer to lift the hub pause; then resume the existing lab locally."
                                       if paused or context.frozen() else
                                       "In the existing lab folder, run efferents status --submission .; resume with efferents start --submission . --detach. Existing evidence and queues are preserved.")})
    for path in context.paths.labs.glob("*/owner.json"):
        meta = _read(path)
        if meta.get("owner_id") not in ids:
            continue
        lab_id = path.parent.name
        error_path = path.parent / "lab" / "last_traceback.txt"
        error = scrub(error_path.read_text()[-2000:], credentials) if error_path.is_file() else ""
        labs.append({"id": lab_id, "name": lab_id, "execution": "hosted",
                     "status": "paused" if control_flag(context.paths, f"halt_{lab_id}") else "connected",
                     "last_seen": None, "pause_reason": context.hub._message_for(lab_id),
                     "last_error": error or None,
                     "recovery_hint": "Use this lab's Resume or Start control. Restart only its daemon after a code fix; its saved lab directory is retained."})
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "event": {"name": context.cfg.name, "frozen": context.frozen(),
                        "paused": control_flag(context.paths, "pause_all")},
              "labs": labs,
              "sessions": [session for item in owners for session in context.intake.list_sessions(item)],
              "recovery_hint": "Keep the existing lab folder and account. Share this report with the organizer; retrying a failed request or refreshing does not reset research."}
    recent = []
    event_path = context.paths.root / "events.jsonl"
    if event_path.exists():
        from collections import deque
        with event_path.open() as handle:
            for line in deque(handle, maxlen=2000):
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item.get("owner_id") in ids and item.get("event") in {
                    "setup_checkpoint", "request_failed", "proxy_failed", "network_register",
                    "idea_deleted", "lab_deleted",
                }:
                    recent.append({key: item[key] for key in ("ts", "event", "stage", "status", "lab_id") if key in item})
    result["recent_setup_events"] = recent[-50:]
    result["budget_reservations"] = coordinator(context.cfg).reservations(owner.owner_id if owner else None)
    if owner:
        result.update(owner=owner.public(), owner_budget=owner_budget(context.cfg, owner.owner_id))
    else:
        result["owners"] = [{**item.public(), "budget": owner_budget(context.cfg, item.owner_id)}
                            for item in owners]
    return result

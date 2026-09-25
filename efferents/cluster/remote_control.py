"""Durable owner steering over the authenticated lab heartbeat channel."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets
from pathlib import Path

from efferents.cluster.config import write_event
from efferents.dashboard.control import ControlError, STEERING_MODES


def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return []


def _save(path: Path, items: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(path)


def queue_command(hub, owner, lab_id: str, action: str, payload: dict) -> dict:
    hub.require_owner(owner, lab_id)
    if action not in {"steer", "pause", "resume", "deleteidea"}:
        raise ControlError("Start and stop the existing daemon on its owner's machine.", status=409)
    text = str(payload.get("message") or payload.get("reason") or "").strip()
    if action != "steer" and not text:
        text = (f"Delete idea {payload.get('idea_id')} requested by {owner.name}; evidence retained"
                if action == "deleteidea" else f"{action} requested by {owner.name}")
    mode = str(payload.get("mode") or "auto")
    if not text or len(text) > 4000 or "\x00" in text or mode not in STEERING_MODES:
        raise ControlError("Use a steering message of 1–4,000 characters and a valid mode.")
    record = {"id": "cmd_" + secrets.token_hex(12), "action": action, "text": text,
              "mode": mode, "by": f"participant:{owner.name}", "owner_id": owner.owner_id,
              "idea_id": payload.get("idea_id") if action == "deleteidea" else None,
              "ts": datetime.now(timezone.utc).isoformat(), "delivered_at": None}
    path = hub.lab_dir(lab_id) / "commands.json"
    with hub._lock:
        commands = _read(path)
        if sum(item.get("delivered_at") is None for item in commands) >= 100:
            raise ControlError("This lab has 100 undelivered commands. Reconnect its daemon first.", status=409)
        _save(path, [*commands, record])
    write_event(hub.paths, "remote_steering_queued", owner_id=owner.owner_id,
                lab_id=lab_id, command_id=record["id"], action=action)
    return {"ok": True, "queued": action, "command_id": record["id"],
            "delivery": "next heartbeat", "by": record["by"], "recorded_at": record["ts"]}


def pending_commands(hub, owner, lab_id: str, payload: dict) -> list[dict]:
    hub.require_owner(owner, lab_id)
    path = hub.lab_dir(lab_id) / "commands.json"
    raw = payload.get("command_acks")
    acknowledged = {item for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()
    with hub._lock:
        commands = _read(path)
        changed = False
        for item in commands:
            if item["id"] in acknowledged and not item.get("delivered_at"):
                item["delivered_at"] = datetime.now(timezone.utc).isoformat()
                changed = True
                write_event(hub.paths, "remote_steering_delivered", lab_id=lab_id,
                            owner_id=owner.owner_id, command_id=item["id"])
        if changed:
            _save(path, commands)
        return [item for item in commands if not item.get("delivered_at")][:100]


def command_acks(lab_root: Path) -> list[str]:
    from efferents.steer import read_steering
    return [item["remote_command_id"] for item in read_steering(lab_root)
            if item.get("remote_command_id")]


def apply_commands(submission: Path, lab_root: Path, commands: list[dict]) -> None:
    """Queue each command once in the existing auditable local steering ledger."""
    from efferents import steer
    seen = set(command_acks(lab_root))
    for item in commands:
        identifier = item.get("id")
        action = item.get("action")
        if not identifier or identifier in seen or action not in {"steer", "pause", "resume", "deleteidea"}:
            continue
        mode = item.get("mode", "auto")
        if mode not in STEERING_MODES:
            continue
        if action == "deleteidea":
            from efferents.lifecycle import remove
            if not isinstance(item.get("idea_id"), str) or not item["idea_id"]:
                continue
            remove(lab_root, by=item["by"], student_id=item["idea_id"])
        steer.steer(submission, lab_root=lab_root, text=item["text"], by=item["by"],
                    action=None if action in {"steer", "deleteidea"} else action,
                    extra={"remote_command_id": identifier, "mode": mode})
        if mode != "auto":
            path = submission / "context" / "research_log.md"
            with path.open("a") as handle:
                handle.write(f"\n## {item['ts']} — Owner steering from event hub\n\n{item['text']}\n\nforce_mode: {mode}\n")
        seen.add(identifier)


def command_history(hub, lab_id: str) -> list[dict]:
    return [{"ts": item["ts"], "text": item["text"], "by": item["by"],
             "action": item["action"], "ack": item.get("delivered_at"),
             "remote_command_id": item["id"]}
            for item in _read(hub.lab_dir(lab_id) / "commands.json")[-100:]]

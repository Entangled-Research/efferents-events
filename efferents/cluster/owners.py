"""Participant identities: join code + chosen name → owner token cookie.

Owners are stored in one JSON file the server owns (mode 0600). The token is
the only credential; it travels in an HttpOnly cookie and in the owner link
(``/?owner=<token>``) a participant keeps to come back as themselves.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path

from efferents.dashboard.control import ControlError

COOKIE_NAME = "efferents_owner"
_MAX_NAME = 40


@dataclass
class Owner:
    owner_id: str
    name: str
    token: str
    joined_at: str
    labs: list[str] = field(default_factory=list)
    ip: str | None = None

    def public(self) -> dict:
        return {"id": self.owner_id, "name": self.name, "labs": list(self.labs)}


def validate_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ControlError("Pick a name so other labs can see who steers this one.")
    if len(name) > _MAX_NAME:
        raise ControlError(f"Names are at most {_MAX_NAME} characters.")
    if not name.isprintable() or any(ch in name for ch in "<>\"'`{}"):
        raise ControlError("Names may only use plain printable characters.")
    return name


class OwnerStore:
    def __init__(self, path: Path, *, max_age_hours: float = 12.0):
        self.path = Path(path)
        self.max_age = timedelta(hours=float(max_age_hours))
        self._lock = threading.RLock()
        self._owners: dict[str, Owner] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        for oid, raw in (data.get("owners") or {}).items():
            try:
                self._owners[oid] = Owner(
                    owner_id=oid, name=raw["name"], token=raw["token"],
                    joined_at=raw.get("joined_at", ""), labs=list(raw.get("labs") or []),
                    ip=raw.get("ip"),
                )
            except (KeyError, TypeError):
                continue

    def _save(self) -> None:
        payload = {"version": 1, "owners": {
            oid: {k: v for k, v in asdict(o).items() if k != "owner_id"}
            for oid, o in self._owners.items()
        }}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # --- queries -----------------------------------------------------------------

    def all(self) -> list[Owner]:
        with self._lock:
            return list(self._owners.values())

    def by_id(self, owner_id: str) -> Owner | None:
        with self._lock:
            return self._owners.get(owner_id)

    def by_token(self, token: str | None) -> Owner | None:
        if not token:
            return None
        with self._lock:
            for owner in self._owners.values():
                if secrets.compare_digest(owner.token, token):
                    return owner if not self._expired(owner) else None
        return None

    def _expired(self, owner: Owner) -> bool:
        if self.max_age.total_seconds() <= 0:
            return False
        try:
            joined = datetime.fromisoformat(owner.joined_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) - joined > self.max_age

    # --- mutations ---------------------------------------------------------------

    def join(self, name: str, *, ip: str | None = None) -> Owner:
        name = validate_name(name)
        with self._lock:
            taken = {o.name.casefold() for o in self._owners.values()}
            if name.casefold() in taken:
                raise ControlError(
                    f"The name {name!r} is taken; add an initial or a number.", status=409
                )
            owner = Owner(
                owner_id=secrets.token_hex(4),
                name=name,
                token=secrets.token_urlsafe(32),
                joined_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ip=ip,
            )
            self._owners[owner.owner_id] = owner
            self._save()
            return owner

    def add_lab(self, owner_id: str, lab_id: str) -> None:
        with self._lock:
            owner = self._owners[owner_id]
            if lab_id not in owner.labs:
                owner.labs.append(lab_id)
                self._save()

    def owner_of(self, lab_id: str) -> Owner | None:
        with self._lock:
            for owner in self._owners.values():
                if lab_id in owner.labs:
                    return owner
        return None


# --- cookies -----------------------------------------------------------------------

def build_cookie(token: str, *, max_age_s: int, secure: bool) -> str:
    parts = [
        f"{COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={int(max_age_s)}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def token_from_cookie_header(header: str | None) -> str | None:
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:  # malformed cookie header: treat as anonymous
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel is not None else None

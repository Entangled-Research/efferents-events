"""Participant identities: join code + chosen name → owner token cookie.

Owners are stored in one JSON file the server owns (mode 0600). The token is
a short-lived credential sent in an HttpOnly cookie or owner link. A separate
hashed recovery key restores the identity and renews access after expiration.
"""

from __future__ import annotations

import json
import hashlib
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
    recovery_hash: str | None = None
    renewed_at: str | None = None

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
    def __init__(self, path: Path, *, max_age_hours: float = 48.0):
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
                    recovery_hash=raw.get("recovery_hash"),
                    renewed_at=raw.get("renewed_at"),
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
            joined = datetime.fromisoformat(owner.renewed_at or owner.joined_at)
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
                    f"The name {name!r} already has an identity. Use Sign in with your saved key or token; otherwise ask the organizer for help.", status=409
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

    def create_recovery_key(self, owner_id: str) -> str:
        """Issue a durable high-entropy credential; only its hash is persisted."""
        with self._lock:
            owner = self._owners[owner_id]
            key = "er_" + secrets.token_urlsafe(32)
            owner.recovery_hash = hashlib.sha256(key.encode()).hexdigest()
            self._save()
            return key

    def recover(self, credential: str) -> Owner:
        credential = credential.strip()
        if not credential or len(credential) > 512:
            raise ControlError("Invalid or expired sign-in credential. Use your saved recovery key.", status=401)
        with self._lock:
            digest = hashlib.sha256(credential.encode()).hexdigest()
            for owner in self._owners.values():
                if owner.recovery_hash and secrets.compare_digest(owner.recovery_hash, digest):
                    # Keep identity, ownership, spend and the lab's configured token.
                    owner.renewed_at = datetime.now(timezone.utc).isoformat()
                    self._save()
                    return owner
            owner = self.by_token(credential)
            if owner is not None:
                return owner
        raise ControlError("Invalid or expired sign-in credential. Use your saved recovery key.", status=401)

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

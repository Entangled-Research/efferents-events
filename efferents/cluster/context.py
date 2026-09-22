"""Everything the cluster server shares across requests."""

from __future__ import annotations

import os

import secrets
import threading
from functools import partial
from typing import Any

from efferents.agents.model_client import make_client
from efferents.cluster.budget import cluster_spend
from efferents.cluster.config import (
    ClusterConfig,
    daemon_env,
    is_frozen,
    write_event,
)
from efferents.cluster.edges import derive_edges
from efferents.cluster.intake import IntakeStore
from efferents.cluster.labs import create_lab
from efferents.cluster.limits import RateLimiter
from efferents.cluster.network import NetworkHub
from efferents.cluster.owners import Owner, OwnerStore
from efferents.cluster.proxy import ModelProxy
from efferents.cluster.tracks import Track, load_tracks
from efferents.dashboard.control import ConnectedLab, ControlContext, ControlError


class ClusterContext:
    def __init__(
        self,
        cfg: ClusterConfig,
        *,
        tracks: dict[str, Track] | None = None,
        client_factory=None,
    ):
        self.cfg = cfg
        self.paths = cfg.paths
        self.tracks = tracks if tracks is not None else load_tracks(cfg.tracks_path)
        self.owners = OwnerStore(self.paths.owners, max_age_hours=cfg.session.max_age_hours)
        self.control = ControlContext()
        self.control.extra_edges = partial(derive_edges, cluster_dir=self.paths.root)
        self.hub = NetworkHub(cfg, self.tracks)
        self.control.extra_labs = self.hub.portfolio_rows
        self.control.extra_evidence = self.hub.network_evidence
        self.proxy = ModelProxy(cfg)
        self.network_limiter = RateLimiter(120, 60.0)
        factory = client_factory or (lambda budget: make_client(budget=budget))
        self.intake = IntakeStore(cfg, self.tracks, client_factory=factory)
        self.join_limiter = RateLimiter(5, 60.0)
        self.message_limiter = RateLimiter(12, 60.0)
        self.mutation_limiter = RateLimiter(30, 60.0)
        self._spend_lock = threading.Lock()
        self._spend_cache: tuple[float, dict] | None = None

    # --- identity ------------------------------------------------------------------

    def join(self, code: str, name: str, *, ip: str | None) -> Owner:
        if not self.join_limiter.allow(ip or "unknown"):
            raise ControlError("Too many join attempts; wait a minute.", status=429)
        supplied = (code or "").strip()
        if not supplied or not secrets.compare_digest(supplied, self.cfg.join_code):
            raise ControlError("That join code is not right.", status=403)
        owner = self.owners.join(name, ip=ip)
        write_event(self.paths, "join", owner_id=owner.owner_id, name=owner.name)
        return owner

    def owner_from_token(self, token: str | None) -> Owner | None:
        return self.owners.by_token(token)

    def upstream_key(self, provider: str = "anthropic") -> str:
        if provider == "openai":
            key = os.environ.get("EFFERENTS_AZURE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        else:
            key = os.environ.get("EFFERENTS_PROXY_UPSTREAM_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
        if not key:
            raise ControlError("The hub has no upstream model key configured.", status=503)
        return key

    def owns(self, owner: Owner | None, lab: ConnectedLab) -> bool:
        if owner is None:
            return False
        if lab.owner_id is not None:
            return lab.owner_id == owner.owner_id
        return lab.cfg.lab_id in owner.labs

    # --- summary payloads ----------------------------------------------------------

    def spend(self) -> dict:
        import time
        with self._spend_lock:
            now = time.monotonic()
            if self._spend_cache is not None and now - self._spend_cache[0] < 5.0:
                return self._spend_cache[1]
            value = cluster_spend(self.paths)
            value["cap"] = self.cfg.caps.cluster_total_usd
            self._spend_cache = (now, value)
            return value

    def frozen(self) -> bool:
        return is_frozen(self.paths)

    def cluster_payload(self, owner: Owner | None) -> dict:
        payload: dict[str, Any] = {
            "name": self.cfg.name,
            "joined": owner is not None,
            "frozen": self.frozen(),
            "people": len(self.owners.all()),
            "tracks": len(self.tracks),
        }
        if owner is not None:
            payload.update({
                "owner": owner.public(),
                "owner_link": f"/?owner={owner.token}",
                "network_token": owner.token,
                "proxy_spend_usd": round(self.proxy.spend(owner.owner_id), 4),
                "proxy_cap_usd": self.cfg.proxy.cap_per_owner_usd,
                "install_ref": self.cfg.network.install_ref,
                "my_labs": list(owner.labs),
                "spend": self.spend(),
                "limits": {
                    "labs_per_owner": self.cfg.labs.max_per_owner,
                    "sessions_per_owner": self.cfg.intake.max_sessions_per_owner,
                    "intake_cap_usd": self.cfg.intake.cap_per_owner_usd,
                },
                "auto_start": self.cfg.labs.auto_start,
            })
        return payload

    # --- lab creation from an intake session -----------------------------------

    def create_lab_from_session(
        self, owner: Owner, session_id: str, *, lab_id: str | None,
        falsifiers: list[dict] | None, start: bool | None,
    ) -> dict:
        if self.frozen():
            raise ControlError("The event budget is frozen; no new labs.", status=409)
        session_payload = self.intake.get(owner, session_id)
        session = session_payload["session"]
        if session["state"] != "bound":
            raise ControlError("Choose a track before creating the lab.", status=409)
        track = self.tracks.get(session["track_id"] or "")
        if track is None:
            raise ControlError("The chosen track no longer exists.", status=409)
        binding = session.get("binding") or {}
        proposed = binding.get("falsifiers") or []
        if falsifiers is None:
            chosen = list(proposed)
        else:
            # Participants may untick rules, never invent them.
            allowed = {r.get("id"): r for r in proposed}
            chosen = []
            for rule in falsifiers:
                rid = rule.get("id") if isinstance(rule, dict) else rule
                if rid not in allowed:
                    raise ControlError("Only the proposed falsifier rules can be kept.")
                chosen.append(allowed[rid])
        from efferents.cluster.intake import Session, Draft  # noqa: PLC0415
        sess_obj = Session(draft=Draft(**session["draft"]),
                           **{k: v for k, v in session.items() if k != "draft"})
        lab = create_lab(
            self.cfg,
            track=track,
            owner=owner,
            hypothesis_text=session["draft"]["text"],
            first_claim=session["first_claim"],
            lab_id=lab_id,
            falsifiers=chosen,
            design_notes=self.intake.design_notes(sess_obj),
            session_id=session_id,
        )
        self.owners.add_lab(owner.owner_id, lab.cfg.lab_id)
        self.intake.mark_created(owner, session_id, lab.cfg.lab_id)
        self.control.labs.invalidate(lab.cfg.lab_id)
        self.control._portfolio_cache.invalidate()
        started = False
        error = None
        should_start = self.cfg.labs.auto_start if start is None else bool(start)
        if should_start:
            try:
                self.control.start_lab(lab, True, env_extra=self.daemon_env())
                started = True
                write_event(self.paths, "start", owner_id=owner.owner_id, lab_id=lab.cfg.lab_id)
            except ControlError as exc:
                error = str(exc)
        return {
            "lab_id": lab.cfg.lab_id,
            "started": started,
            "start_error": error,
            "control": self.control.lab_info(lab),
            "session": self.intake.get(owner, session_id)["session"],
        }

    def daemon_env(self) -> dict[str, str]:
        return daemon_env(self.cfg)

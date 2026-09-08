"""The hosted dashboard: identity, intake and lab creation on top of the
lab-scoped dashboard server."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from efferents.cluster.config import ClusterConfig, activate_environment, load_cluster_config
from efferents.cluster.context import ClusterContext
from efferents.cluster.owners import Owner, build_cookie, token_from_cookie_header
from efferents.dashboard.control import ConnectedLab, ControlError
from efferents.dashboard.server import DashboardHandler, make_server

_SESSION_ROUTE = re.compile(r"^/api/intake/sessions/(?P<sid>s_[0-9a-f]{12})(?:/(?P<verb>[a-z]+))?$")


class ClusterHandler(DashboardHandler):
    cluster: ClusterContext

    def __init__(self, *args, cluster: ClusterContext, **kwargs):
        self.cluster = cluster
        self._pending_cookie: str | None = None
        self._owner: Owner | None = None
        self._owner_loaded = False
        super().__init__(*args, **kwargs)

    # --- identity hooks -------------------------------------------------------------

    def _session(self) -> Owner | None:
        if not self._owner_loaded:
            token = token_from_cookie_header(self.headers.get("Cookie"))
            self._owner = self.cluster.owner_from_token(token)
            self._owner_loaded = True
        return self._owner

    def _require_viewer(self) -> None:
        if self._session() is None:
            raise ControlError("Join the event with the code first.", status=401)

    def _require_owner(self, lab: ConnectedLab) -> None:
        owner = self._session()
        if owner is None:
            raise ControlError("Join the event with the code first.", status=401)
        if not self.cluster.owns(owner, lab):
            raise ControlError("Only this lab's owner can steer it.", status=403)
        if not self.cluster.mutation_limiter.allow(owner.owner_id):
            raise ControlError("Too many control requests; slow down.", status=429)

    def _actor(self) -> str:
        owner = self._session()
        return f"participant:{owner.name}" if owner else "participant"

    def _daemon_env(self) -> dict[str, str] | None:
        return self.cluster.daemon_env()

    def _client_ip(self) -> str:
        if self.cluster.cfg.session.trust_proxy:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def _set_owner_cookie(self, owner: Owner) -> None:
        cfg = self.cluster.cfg.session
        self._pending_cookie = build_cookie(
            owner.token,
            max_age_s=int(cfg.max_age_hours * 3600),
            secure=cfg.secure_cookies,
        )

    def _extra_headers(self) -> None:
        if self._pending_cookie:
            self.send_header("Set-Cookie", self._pending_cookie)

    def _control_payload(self) -> dict:
        owner = self._session()
        payload = self.control.info() if owner is not None else {"connected": False}
        payload["mode"] = "cluster"
        payload["paused_demo"] = False
        payload["modes"] = []
        payload["cluster"] = self.cluster.cluster_payload(owner)
        if owner is not None:
            payload["csrf_token"] = self.csrf_token
        return payload

    # --- GET -------------------------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parts = urlsplit(self.path)
        query = parse_qs(parts.query) if parts.query else {}
        if parts.path in ("/", "/index.html") and "owner" in query:
            token = (query.get("owner") or [None])[0]
            owner = self.cluster.owner_from_token(token)
            if owner is not None:
                self._set_owner_cookie(owner)
                return self._redirect("/#network")
            return self._redirect("/#join")
        return super().do_GET()

    def _extra_get(self, path: str) -> bool:
        if path == "/api/tracks":
            self._require_viewer()
            self._send_json([t.payload() for t in self.cluster.tracks.values()])
            return True
        if path == "/api/intake/sessions":
            owner = self._require_joined()
            self._send_json(self.cluster.intake.list_sessions(owner))
            return True
        match = _SESSION_ROUTE.match(path)
        if match and match.group("verb") is None:
            owner = self._require_joined()
            self._send_json(self.cluster.intake.get(owner, match.group("sid")))
            return True
        if path in ("/api/connect", "/api/labs/select"):
            self.send_error(404)
            return True
        return False

    def _require_joined(self) -> Owner:
        owner = self._session()
        if owner is None:
            raise ControlError("Join the event with the code first.", status=401)
        return owner

    # --- POST ------------------------------------------------------------------------

    def _extra_post_precsrf(self, path: str) -> bool:
        if path != "/api/join":
            return False
        payload = self._read_json()
        owner = self.cluster.join(
            str(payload.get("code") or ""), str(payload.get("name") or ""),
            ip=self._client_ip(),
        )
        self._owner, self._owner_loaded = owner, True
        self._set_owner_cookie(owner)
        self._send_json({
            "owner": owner.public(),
            "owner_link": f"/?owner={owner.token}",
            "csrf_token": self.csrf_token,
            "cluster": self.cluster.cluster_payload(owner),
        })
        return True

    def _extra_post(self, path: str, payload: dict) -> bool:
        if path in ("/api/connect", "/api/labs/select", "/api/steer",
                    "/api/lab/start", "/api/lab/stop"):
            # Cluster mode has no default lab and no repository connect.
            self.send_error(404)
            return True
        if not path.startswith("/api/intake/"):
            return False
        owner = self._require_joined()
        intake = self.cluster.intake
        if path == "/api/intake/sessions":
            self._send_json(intake.create_session(owner))
            return True
        match = _SESSION_ROUTE.match(path)
        if not match or match.group("verb") is None:
            self.send_error(404)
            return True
        sid, verb = match.group("sid"), match.group("verb")
        if verb == "messages":
            if not self.cluster.message_limiter.allow(owner.owner_id):
                raise ControlError("Too many messages per minute; slow down.", status=429)
            result = intake.run_turn(owner, sid, str(payload.get("text") or ""))
        elif verb == "approve":
            result = intake.approve(owner, sid)
        elif verb == "bind":
            result = intake.bind(owner, sid, str(payload.get("track_id") or ""))
        elif verb == "create":
            falsifiers = payload.get("falsifiers")
            if falsifiers is not None and not isinstance(falsifiers, list):
                raise ControlError("falsifiers must be a list of rule ids.")
            start = payload.get("start")
            result = self.cluster.create_lab_from_session(
                owner, sid,
                lab_id=(str(payload.get("lab_id")).strip() or None) if payload.get("lab_id") else None,
                falsifiers=falsifiers,
                start=start if isinstance(start, bool) else None,
            )
        elif verb == "abandon":
            result = intake.abandon(owner, sid)
        else:
            self.send_error(404)
            return True
        self._send_json(result)
        return True


def make_cluster_server(cfg: ClusterConfig, *, host: str = "127.0.0.1", port: int = 8800,
                        context: ClusterContext | None = None, read_ttl_s: float = 2.0):
    context = context or ClusterContext(cfg)
    return make_server(
        None, port, host=host, control=context.control, handler_cls=ClusterHandler,
        read_ttl_s=read_ttl_s, handler_kwargs={"cluster": context},
    ), context


def serve_cluster(root: Path, *, host: str = "127.0.0.1", port: int = 8800,
                  open_browser: bool = False) -> int:
    cfg = load_cluster_config(root)
    activate_environment(cfg)
    httpd, context = make_cluster_server(cfg, host=host, port=port)
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"http://{shown}:{httpd.server_address[1]}/"
    serve_json = cfg.paths.root / "serve.json"
    serve_json.write_text(json.dumps({
        "pid": __import__("os").getpid(), "port": httpd.server_address[1], "url": url,
    }))
    print(f"efferents cluster '{cfg.name}': {url}  ({len(context.tracks)} track(s), "
          f"{len(context.owners.all())} participant(s); Ctrl-C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
        if serve_json.exists():
            serve_json.unlink()
    return 0

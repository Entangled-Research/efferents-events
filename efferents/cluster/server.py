"""The hosted dashboard: identity, intake and lab creation on top of the
lab-scoped dashboard server."""

from __future__ import annotations

import json
import os
import secrets
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from efferents.cluster.config import ClusterConfig, activate_environment, load_cluster_config, write_event
from efferents.cluster.context import ClusterContext
from efferents.cluster.binding import propose_falsifiers
from efferents.cluster.budget import owner_intake_budget
from efferents.cluster.intake_md import render_intake_md
from efferents.cluster.owners import Owner, build_cookie, token_from_cookie_header
from efferents.cluster.proxy import MAX_PROXY_BODY, OPENAI_PROXY_PREFIX, PROXY_PREFIX, ProxyError
from efferents.dashboard.control import ConnectedLab, ControlError
from efferents.dashboard.server import LAB_ID_PATTERN, DashboardHandler, make_server

_SESSION_ROUTE = re.compile(r"^/api/intake/sessions/(?P<sid>s_[0-9a-f]{12})(?:/(?P<verb>[a-z]+))?$")
_NET_LAB_ROUTE = re.compile(rf"^/api/network/labs/(?P<lab_id>{LAB_ID_PATTERN})/(?P<verb>[a-z]+)$")
_NET_TRACK_ROUTE = re.compile(r"^/api/network/tracks/(?P<track_id>[A-Za-z0-9][A-Za-z0-9._-]{0,63})\.tar\.gz$")
_LAB_VIEW_ROUTE = re.compile(rf"^/api/labs/(?P<lab_id>{LAB_ID_PATTERN})/(?P<kind>control|state|runs|papers|activity|evidence|verdict|ideas/[A-Za-z0-9_-]+)$")
_NETWORK_BODY = 1024 * 1024


class ClusterHandler(DashboardHandler):
    cluster: ClusterContext

    def __init__(self, *args, cluster: ClusterContext, **kwargs):
        self.cluster = cluster
        self._pending_cookie: str | None = None
        self._owner: Owner | None = None
        self._owner_loaded = False
        super().__init__(*args, **kwargs)

    # --- identity hooks -------------------------------------------------------------

    def _bearer(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        return None

    def _session(self) -> Owner | None:
        if not self._owner_loaded:
            token = self._bearer() or token_from_cookie_header(self.headers.get("Cookie"))
            self._owner = self.cluster.owner_from_token(token)
            self._owner_loaded = True
        return self._owner

    def _base_url(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost"
        return f"{proto}://{host}"

    def _remote_lab_id(self, path: str) -> tuple[str, str] | None:
        m = _LAB_VIEW_ROUTE.match(path)
        if not m:
            return None
        lab_id = m.group("lab_id")
        if (self.cluster.hub.root / lab_id / "registration.json").is_file():
            return lab_id, m.group("kind")
        return None

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
                return self._redirect("/#join")
            return self._redirect("/?signin=expired#join")
        return super().do_GET()

    def _require_admin(self) -> None:
        expected = os.environ.get("EFFERENTS_ADMIN_TOKEN", "")
        supplied = self._bearer() or ""
        if not expected or not supplied or not secrets.compare_digest(expected.encode(), supplied.encode()):
            raise ControlError("Organizer authentication required.", status=403)

    def _extra_get(self, path: str) -> bool:
        if path == "/api/admin/budget/reservations":
            from efferents.cluster.budget import coordinator
            self._require_admin()
            self._send_json({"reservations": coordinator(self.cluster.cfg).reservations(),
                             "recovery": "Inspect the provider's request and billing records before releasing a held reservation. Holds never expire automatically."})
            return True
        if path in ("/api/diagnostics", "/api/admin/diagnostics"):
            from efferents.cluster.diagnostics import diagnostics
            if path.startswith("/api/admin/"):
                self._require_admin()
                owner = None
            else:
                owner = self._require_joined()
            self._send_json(diagnostics(self.cluster, owner))
            return True
        if path == "/intake.md":
            body = render_intake_md(self.cluster.cfg, self._base_url()).encode()
            self._send_bytes(body, "text/markdown; charset=utf-8")
            return True
        if path.startswith("/api/network/"):
            owner = self._require_joined()
            self._network_get(owner, path)
            return True
        artifact = re.fullmatch(r"/api/labs/([A-Za-z0-9._-]+)/artifacts/([a-f0-9]{64})", path)
        if artifact:
            owner = self._require_joined()
            lab_id, digest = artifact.groups()
            self.cluster.hub.registration(lab_id)
            snapshot_path = self.cluster.hub.lab_dir(lab_id) / "owner-evals.json"
            snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.is_file() else {}
            encoded = snapshot.get("images", {}).get(digest)
            if encoded is None:
                raise ControlError("Unknown eval image", status=404)
            import base64
            self._send_bytes(base64.b64decode(encoded), "image/png")
            return True
        remote = self._remote_lab_id(path)
        if remote is not None:
            owner = self._require_joined()
            lab_id, kind = remote
            self._send_json(self.cluster.hub.lab_view(lab_id, kind, owner_id=self._session().owner_id))
            return True
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
            if self._bearer():
                raise ControlError(
                    "Network token invalid or expired. Copy the current network token "
                    "from the event page; the event join code is different.",
                    status=401,
                )
            raise ControlError("Join the event with the code first.", status=401)
        return owner

    def _network_get(self, owner: Owner, path: str) -> None:
        hub = self.cluster.hub
        if path == "/api/network/package":
            from efferents.cluster.network import participant_wheel
            wheel = participant_wheel()
            if wheel is None:
                raise ControlError("No tested participant package on this hub", status=404)
            return self._send_file(wheel)
        if path == "/api/network/config":
            return self._send_json(hub.config_payload(owner, self._base_url()))
        if path == "/api/network/feed":
            lab_id = parse_qs(urlsplit(self.path).query).get("lab_id", [None])[0]
            return self._send_bytes(hub.subscribed_feed(owner, lab_id).encode(), "text/markdown; charset=utf-8")
        m = _NET_TRACK_ROUTE.match(path)
        if m:
            return self._send_bytes(hub.track_tarball(m.group("track_id")), "application/gzip")
        m = _NET_LAB_ROUTE.match(path)
        if m and m.group("verb") == "reviews":
            return self._send_bytes(hub.reviews_for(owner, m.group("lab_id")).encode(),
                                    "text/markdown; charset=utf-8")
        self.send_error(404)

    # --- POST ------------------------------------------------------------------------

    def _extra_post_precsrf(self, path: str) -> bool:
        if path == "/api/admin/accounts/merge":
            self._require_admin()
            payload = self._read_json(8192)
            sources = payload.get("source_ids")
            if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
                raise ControlError("source_ids must be a list of account ids.")
            self._send_json(self.cluster.merge_accounts(
                str(payload.get("target_id") or ""), sources,
                reason=str(payload.get("reason") or "")))
            return True
        # Machine clients (daemons, agents) authenticate with a bearer token,
        # which browsers never attach on their own, so CSRF does not apply.
        if path.startswith(PROXY_PREFIX + "/"):
            self._proxy(path[len(PROXY_PREFIX):], provider="anthropic")
            return True
        if path.startswith(OPENAI_PROXY_PREFIX + "/"):
            self._proxy(path[len(OPENAI_PROXY_PREFIX):], provider="openai")
            return True
        if path.startswith("/api/network/") and self._bearer():
            owner = self._require_joined()
            if not self.cluster.network_limiter.allow(owner.owner_id):
                raise ControlError("Too many hub requests; slow down.", status=429)
            self._network_post(owner, path, self._read_json(_NETWORK_BODY))
            return True
        if path == "/api/login":
            if not self.cluster.login_limiter.allow(self._client_ip()):
                raise ControlError("Too many sign-in attempts; wait a minute.", status=429)
            payload = self._read_json(4096)
            credential = str(payload.get("credential") or "").strip()
            if "?owner=" in credential:
                credential = (parse_qs(urlsplit(credential).query).get("owner") or [""])[0]
            owner = self.cluster.owners.recover(credential)
            write_event(self.cluster.paths, "sign_in", owner_id=owner.owner_id)
            self._owner, self._owner_loaded = owner, True
            self._set_owner_cookie(owner)
            self._send_json({"owner": owner.public(), "csrf_token": self.csrf_token,
                             "cluster": self.cluster.cluster_payload(owner)})
            return True
        if path != "/api/join":
            return False
        payload = self._read_json()
        owner = self.cluster.join(
            str(payload.get("code") or ""), str(payload.get("name") or ""),
            ip=self._client_ip(),
        )
        recovery_key = self.cluster.owners.create_recovery_key(owner.owner_id)
        self._owner, self._owner_loaded = owner, True
        self._set_owner_cookie(owner)
        self._send_json({
            "recovery_key": recovery_key,
            "owner": owner.public(),
            "owner_link": f"/?owner={owner.token}",
            "csrf_token": self.csrf_token,
            "cluster": self.cluster.cluster_payload(owner),
        })
        return True

    def _network_post(self, owner: Owner, path: str, payload: dict) -> None:
        hub = self.cluster.hub
        if path == "/api/network/labs":
            result = hub.register(owner, payload)
            self.cluster.owners.add_lab(owner.owner_id, result["lab_id"])
            return self._send_json(result)
        if path == "/api/network/bind":
            track = self.cluster.tracks.get(str(payload.get("track_id") or ""))
            if track is None:
                raise ControlError("Unknown track.", status=404)
            hypothesis = str(payload.get("hypothesis") or "")
            if not hypothesis.strip():
                raise ControlError("Send the hypothesis text.")
            budget = owner_intake_budget(self.cluster.cfg, owner.owner_id)
            client = self.cluster.intake._client_factory(budget)
            try:
                binding = propose_falsifiers(hypothesis, track, client=client,
                                             model=self.cluster.cfg.model, budget=budget)
            except Exception as exc:
                budget.finish_error(exc)
                raise
            finally:
                budget.release()
            return self._send_json(binding.to_dict())
        m = _NET_LAB_ROUTE.match(path)
        if m:
            lab_id, verb = m.group("lab_id"), m.group("verb")
            if verb == "receipts":
                return self._send_json(hub.acknowledge_feed(owner, lab_id, payload))
            if verb == "heartbeat":
                return self._send_json(hub.heartbeat(owner, lab_id, payload))
            if verb == "journal":
                return self._send_json(hub.push_journal(owner, lab_id, payload))
        self.send_error(404)

    def _proxy(self, upstream_path: str, *, provider: str = "anthropic") -> None:
        token = self.headers.get("x-api-key") or self._bearer()
        owner = self.cluster.owner_from_token(token)
        if owner is None:
            raise ControlError("Unknown network token.", status=401)
        body = self._read_body(MAX_PROXY_BODY)
        headers = {k: v for k, v in self.headers.items()}
        try:
            status, payload, resp_headers = self.cluster.proxy.forward(
                owner_id=owner.owner_id, path=upstream_path, body=body, headers=headers,
                api_key=self.cluster.upstream_key(provider), provider=provider,
            )
        except ProxyError as exc:
            self._send_bytes(exc.body(), "application/json", status=exc.status)
            return
        extra = {k: v for k, v in resp_headers.items() if k != "content-type"}
        self._send_bytes(payload, resp_headers.get("content-type", "application/json"),
                         status=status, extra_headers=extra)

    def _extra_post(self, path: str, payload: dict) -> bool:
        if path == "/api/account/recovery":
            owner = self._require_joined()
            if not self.cluster.mutation_limiter.allow(owner.owner_id):
                raise ControlError("Too many requests; slow down.", status=429)
            key = self.cluster.owners.create_recovery_key(owner.owner_id)
            write_event(self.cluster.paths, "recovery_key_replaced", owner_id=owner.owner_id)
            self._send_json({"recovery_key": key})
            return True
        if path == "/api/logout":
            self._require_joined()
            self._pending_cookie = build_cookie("", max_age_s=0, secure=self.cluster.cfg.session.secure_cookies)
            self._send_json({"signed_out": True})
            return True
        if path in ("/api/connect", "/api/labs/select", "/api/steer",
                    "/api/lab/start", "/api/lab/stop", "/api/onboard",
                    "/api/lab/trial", "/api/network/observe"):
            # Cluster mode has no default lab and no repository connect.
            self.send_error(404)
            return True
        if re.fullmatch(r"/api/labs/[A-Za-z0-9._-]+/[a-z]+", path) and (self.cluster.hub.root / path.split("/")[3] / "registration.json").is_file():
            owner = self._require_joined()
            from efferents.cluster.remote_control import queue_command
            lab_id, action = path.split("/")[3:5]
            if not self.cluster.mutation_limiter.allow(owner.owner_id):
                raise ControlError("Too many control requests; slow down.", status=429)
            self._send_json(queue_command(self.cluster.hub, owner, lab_id, action, payload))
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
        elif verb == "route":
            result = intake.route(owner, sid)
        elif verb == "bind":
            # Track selection is an automatic routing decision.  Keep the
            # store-level binding helper for internal compatibility, but do
            # not let a participant bypass relevance routing by naming a
            # track in the public intake API.
            raise ControlError(
                "Track selection is automatic; use the route endpoint.",
                status=409,
            )
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

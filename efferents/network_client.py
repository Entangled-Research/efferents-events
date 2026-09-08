"""Daemon-side client for an event hub (the terminal path).

Configured entirely by environment (written into the lab's ``.env`` by the
participant's agent following the hub's ``intake.md``):

    EFFERENTS_NETWORK_URL    https://hub.example.org
    EFFERENTS_NETWORK_TOKEN  the participant's network token

When both are set the orchestrator registers the lab at start, sends a
heartbeat every ``heartbeat_s``, pushes new journal entries and papers,
pulls the shared feed into ``paper/external_journal.md`` and reviews of
this lab into ``paper/incoming_reviews.md``, and honours a pause the hub
asks for. Every call is best-effort: a hub outage never stops the lab.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from efferents.agents import federation

_TIMEOUT_S = 20


def configured() -> bool:
    return bool(os.environ.get("EFFERENTS_NETWORK_URL") and os.environ.get("EFFERENTS_NETWORK_TOKEN"))


class NetworkClient:
    def __init__(self, url: str | None = None, token: str | None = None, *, opener=None):
        self.url = (url or os.environ.get("EFFERENTS_NETWORK_URL", "")).rstrip("/")
        self.token = token or os.environ.get("EFFERENTS_NETWORK_TOKEN", "")
        self._open = opener or urllib.request.urlopen
        self.heartbeat_s = 30.0
        self.pull_s = 120.0
        self._last_heartbeat = 0.0
        self._last_pull = 0.0
        self._pushed: set[tuple[str, str]] = set()
        self.last_error: str | None = None

    # --- transport -------------------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Cookie": f"efferents_owner={self.token}",
                     "Authorization": f"Bearer {self.token}"},
        )
        try:
            with self._open(req, timeout=_TIMEOUT_S) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            self.last_error = f"{e.code} {body}"
            raise
        except (urllib.error.URLError, OSError) as e:
            self.last_error = str(e)
            raise
        self.last_error = None
        if "json" in ctype:
            return json.loads(raw or b"{}")
        return raw.decode(errors="replace")

    # --- high level --------------------------------------------------------------------

    def register(self, *, lab_id: str, domain: str, hypothesis: str, track: str | None) -> dict:
        result = self._request("POST", "/api/network/labs", {
            "lab_id": lab_id, "domain": domain, "hypothesis": hypothesis, "track": track,
            "host": socket.gethostname()[:120],
        })
        self.heartbeat_s = float(result.get("heartbeat_s", self.heartbeat_s))
        self.pull_s = float(result.get("pull_s", self.pull_s))
        return result

    def heartbeat(self, lab_id: str, payload: dict) -> dict:
        return self._request("POST", f"/api/network/labs/{lab_id}/heartbeat", payload)

    def push_journal(self, lab_id: str, paper_dir: Path) -> dict | None:
        journal = paper_dir / "journal.md"
        if not journal.is_file():
            return None
        entries = federation.parse_journal_entries(journal.read_text())
        fresh = [e for e in entries if (e.get("lab_id") or lab_id, e["campaign_id"]) not in self._pushed]
        if not fresh:
            return None
        papers = {}
        for e in fresh:
            paper = paper_dir / f"{e['campaign_id']}.md"
            if paper.is_file():
                papers[e["campaign_id"]] = paper.read_text()
        result = self._request("POST", f"/api/network/labs/{lab_id}/journal",
                               {"journal": journal.read_text(), "papers": papers})
        for e in fresh:
            self._pushed.add((e.get("lab_id") or lab_id, e["campaign_id"]))
        return result

    def pull_feed(self, lab_id: str, paper_dir: Path) -> dict | None:
        text = self._request("GET", "/api/network/feed")
        if not isinstance(text, str) or not text.strip():
            return None
        tmp = paper_dir / ".hub_feed.md"
        paper_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text)
        return federation.consume_external_journal(
            source=tmp, out_path=paper_dir / "external_journal.md", our_lab_id=lab_id,
        )

    def pull_reviews(self, lab_id: str, paper_dir: Path) -> bool:
        text = self._request("GET", f"/api/network/labs/{lab_id}/reviews")
        if not isinstance(text, str) or not text.strip():
            return False
        target = paper_dir / "incoming_reviews.md"
        paper_dir.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_text() == text:
            return False
        target.write_text(text)
        return True

    def due_heartbeat(self) -> bool:
        return time.monotonic() - self._last_heartbeat >= self.heartbeat_s

    def due_pull(self) -> bool:
        return time.monotonic() - self._last_pull >= self.pull_s

    def mark_heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()

    def mark_pull(self) -> None:
        self._last_pull = time.monotonic()

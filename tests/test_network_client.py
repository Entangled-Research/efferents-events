from __future__ import annotations

import io
import json
import shutil
from email.message import Message
from pathlib import Path


from efferents import lab as lab_mod
from efferents import network_client as nc
from efferents.lab import LabConfig

SMOKE = Path(__file__).resolve().parents[1] / "examples" / "smoke-lab"


class FakeHub:
    def __init__(self):
        self.calls = []
        self.pause = False
        self.commands = []
        self.feed = ""
        self.reviews = ""

    def opener(self, req, timeout=0):
        path = req.full_url.split("hub.test", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), path, body, req.get_header("Authorization")))
        if path == "/api/network/labs":
            return self._json({"registered": True, "lab_id": body["lab_id"], "heartbeat_s": 5, "pull_s": 9})
        if path.endswith("/heartbeat"):
            return self._json({"ok": True, "pause": self.pause, "commands": self.commands, "message": "paused by hub" if self.pause else None})
        if path.endswith("/journal"):
            return self._json({"ok": True, "entries_added": len(body.get("papers", {})), "papers_stored": 0})
        if path.startswith("/api/network/feed?"):
            return self._text(self.feed)
        if path.endswith("/receipts"):
            return self._json({"ok": True})
        if path.endswith("/reviews"):
            return self._text(self.reviews)
        raise AssertionError(path)

    @staticmethod
    def _resp(data: bytes, ctype: str):
        r = io.BytesIO(data)
        r.status = 200
        r.headers = Message()
        r.headers["Content-Type"] = ctype
        r.__enter__ = lambda self=r: self
        r.__exit__ = lambda self=r, *a: False
        return r

    def _json(self, obj):
        return self._resp(json.dumps(obj).encode(), "application/json")

    def _text(self, text):
        return self._resp(text.encode(), "text/markdown")


def test_client_register_heartbeat_push_pull(tmp_path):
    hub = FakeHub()
    client = nc.NetworkClient("https://hub.test", "tok", opener=hub.opener)
    out = client.register(lab_id="my-lab", domain="d", hypothesis="---\n---\n", track="t")
    assert out["registered"] and client.heartbeat_s == 5 and client.pull_s == 9
    assert hub.calls[0][3] == "Bearer tok"
    paper = tmp_path / "paper"
    paper.mkdir()
    assert client.push_journal("my-lab", paper) is None  # no journal yet
    (paper / "journal.md").write_text(
        "# J\n\n<!-- ENTRIES BELOW -->\n\n## 2026-09-20 14:00 UTC — c1\n**Lab**: my-lab\n**Headline**: h\n")
    (paper / "c1.md").write_text("# paper\n")
    assert client.push_journal("my-lab", paper)["entries_added"] == 1
    assert client.push_journal("my-lab", paper) is None  # already pushed
    hub.feed = ("# hub\n\n<!-- ENTRIES BELOW -->\n\n## 2026-09-20 14:00 UTC — z1\n"
                "**Lab**: other-lab\n**Headline**: theirs\n\n## 2026-09-20 14:00 UTC — c1\n"
                "**Lab**: my-lab\n**Headline**: h\n")
    pulled = client.pull_feed("my-lab", paper)
    assert pulled["n_added"] == 1 and pulled["n_skipped_self"] == 1
    assert "theirs" in (paper / "external_journal.md").read_text()
    hub.reviews = "# reviews\n"
    assert client.pull_reviews("my-lab", paper) is False
    assert client.pull_reviews("my-lab", paper) is False  # unchanged


def test_orchestrator_hooks_register_heartbeat_and_hub_pause(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    from efferents.steer import read_steering
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    hub = FakeHub()
    monkeypatch.setenv("EFFERENTS_NETWORK_URL", "https://hub.test")
    monkeypatch.setenv("EFFERENTS_NETWORK_TOKEN", "tok")
    monkeypatch.setenv("EFFERENTS_NETWORK_TRACK", "coefficient-sweep")
    monkeypatch.setattr(nc.NetworkClient, "__init__",
                        lambda self, url=None, token=None, opener=None: _init(self, url, token, hub.opener))
    monkeypatch.setattr(orch, "notify_all", lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / "lab", context_dir=sub / "context", dry_run=True,
                          submission_dir=sub)
    assert o.network is not None
    assert hub.calls[0][1] == "/api/network/labs" and hub.calls[0][2]["track"] == "coefficient-sweep"
    assert "registered with the event hub" in (sub / "lab" / "lab_notebook.md").read_text()
    o._maybe_network()  # heartbeat due immediately
    beat = next(c for c in hub.calls if c[1].endswith("/heartbeat"))
    assert beat[2]["status"] == "running" and "edges" in beat[2]
    hub.pause = True
    o.network._last_heartbeat = 0
    o._maybe_network()
    records = read_steering(sub / "lab")
    assert records[-1]["action"] == "pause" and records[-1]["by"] == "event hub"
    hub.pause = False
    o.network._last_heartbeat = 0
    o._maybe_network()
    assert read_steering(sub / "lab")[-1]["action"] == "resume"


def _init(self, url, token, opener):
    import os
    self.url = (url or os.environ.get("EFFERENTS_NETWORK_URL", "")).rstrip("/")
    self.token = token or os.environ.get("EFFERENTS_NETWORK_TOKEN", "")
    self._open = opener
    self.heartbeat_s = 30.0
    self.pull_s = 120.0
    self._last_heartbeat = 0.0
    self._last_pull = 0.0
    self._pushed = set()
    self.last_error = None
    self.liveness_supported = False


def test_unconfigured_daemon_has_no_network(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    monkeypatch.delenv("EFFERENTS_NETWORK_URL", raising=False)
    monkeypatch.delenv("EFFERENTS_NETWORK_TOKEN", raising=False)
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    monkeypatch.setattr(orch, "notify_all", lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / "lab", context_dir=sub / "context", dry_run=True)
    assert o.network is None
    o._maybe_network()  # no-op


def test_owner_resumes_cannot_override_an_active_hub_pause(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    from efferents import steer
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    hub = FakeHub()
    hub.pause = True
    monkeypatch.setenv("EFFERENTS_NETWORK_URL", "https://hub.test")
    monkeypatch.setenv("EFFERENTS_NETWORK_TOKEN", "tok")
    monkeypatch.setattr(nc.NetworkClient, "__init__",
                        lambda self, url=None, token=None, opener=None: _init(self, url, token, hub.opener))
    monkeypatch.setattr(orch, "notify_all", lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / "lab", context_dir=sub / "context", dry_run=True,
                          submission_dir=sub)
    monkeypatch.setattr(o, "_interruptible_sleep", lambda *_: None)
    assert o.step()["event"] == "owner_paused"
    hub.commands = [{"id": "cmd_resume", "action": "resume", "text": "Continue my research",
                     "by": "participant:Ada", "mode": "auto", "ts": "2026-09-23T22:00:00Z"}]
    o.network._last_heartbeat = 0
    assert o.step()["event"] == "owner_paused"
    records = steer.read_steering(sub / "lab")
    owner_resume = next(record for record in records if record.get("remote_command_id") == "cmd_resume")
    assert owner_resume["ack"] and owner_resume["action"] == "resume"
    assert records[-1]["action"] == "pause" and records[-1]["by"] == "event hub"
    assert steer.owner_paused(sub / "lab")
    # A local resume between heartbeats is also recorded and held behind the hub pause.
    steer.steer(sub, lab_root=sub / "lab", text="resume from laptop", by="Ada", action="resume")
    assert o.step()["event"] == "owner_paused"
    assert steer.owner_paused(sub / "lab")
    # Only a later hub response lifting its pause lets its halt clear.
    hub.pause = False
    hub.commands = []
    o.network._last_heartbeat = 0
    o._maybe_network()
    o._enforce_network_pause()
    steer.apply_pending(o)
    assert steer.owner_paused(sub / "lab") is None


def test_lifting_hub_pause_preserves_the_owners_independent_pause(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    from efferents import steer
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    hub = FakeHub()
    monkeypatch.setenv("EFFERENTS_NETWORK_URL", "https://hub.test")
    monkeypatch.setenv("EFFERENTS_NETWORK_TOKEN", "tok")
    monkeypatch.setattr(nc.NetworkClient, "__init__",
                        lambda self, url=None, token=None, opener=None: _init(self, url, token, hub.opener))
    monkeypatch.setattr(orch, "notify_all", lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / "lab", context_dir=sub / "context", dry_run=True,
                          submission_dir=sub)
    monkeypatch.setattr(o, "_interruptible_sleep", lambda *_: None)
    steer.steer(sub, lab_root=sub / "lab", text="Hold my research for review", by="Ada", action="pause")
    assert o.step()["event"] == "owner_paused"
    hub.pause = True
    o.network._last_heartbeat = 0
    assert o.step()["event"] == "owner_paused"
    hub.pause = False
    o.network._last_heartbeat = 0
    assert o.step()["event"] == "owner_paused"
    assert o._network_paused is False
    assert "owner's pause remains" in steer.read_steering(sub / "lab")[-1]["text"]


def test_applied_steering_reports_actual_state_before_sleep_or_work(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    from efferents import steer
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    hub = FakeHub()
    monkeypatch.setenv("EFFERENTS_NETWORK_URL", "https://hub.test")
    monkeypatch.setenv("EFFERENTS_NETWORK_TOKEN", "tok")
    monkeypatch.setattr(nc.NetworkClient, "__init__",
                        lambda self, url=None, token=None, opener=None: _init(self, url, token, hub.opener))
    monkeypatch.setattr(orch, "notify_all", lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / "lab", context_dir=sub / "context", dry_run=True,
                          submission_dir=sub)
    sleeps = []
    def paused_sleep(_):
        beat = [call[2] for call in hub.calls if call[1].endswith('/heartbeat')][-1]
        sleeps.append(beat)
        assert beat['status'] == 'paused'
        assert 'pause-id' in beat['command_acks']
    monkeypatch.setattr(o, "_interruptible_sleep", paused_sleep)
    steer.steer(sub, text="Pause safely", action="pause", extra={"remote_command_id": "pause-id"})
    assert steer.step_hook(o) is True
    assert sleeps
    steer.steer(sub, text="Continue", action="resume", extra={"remote_command_id": "resume-id"})
    assert steer.step_hook(o) is False
    beat = [call[2] for call in hub.calls if call[1].endswith('/heartbeat')][-1]
    assert beat['status'] == 'running' and 'resume-id' in beat['command_acks']
    assert set(o._network_heartbeat_payload()['command_acks']) == {'pause-id', 'resume-id'}
    assert all(record['ack'] for record in steer.read_steering(sub / 'lab'))


def test_liveness_worker_never_applies_control_or_overwrites_snapshot(tmp_path):
    import threading
    hub = FakeHub()
    received = threading.Event()
    def opener(request, timeout=0):
        result = hub.opener(request, timeout)
        received.set()
        return result
    client = nc.NetworkClient('https://hub.test', 'tok', opener=opener)
    # An old server must never receive the new partial-heartbeat format.
    assert client.start_liveness('my-lab', interval_s=.01) is None
    client.liveness_supported = True
    worker = client.start_liveness('my-lab', interval_s=.01)
    try:
        assert received.wait(1)
    finally:
        worker.stop()
    assert not worker.thread.is_alive()
    assert worker.client is not client
    assert all(call[2] == {'liveness_only': True} for call in hub.calls)
    assert client._last_heartbeat == 0  # Main-thread scheduling stays independent.


def test_run_reports_stopped_after_liveness_worker_shutdown(tmp_path, monkeypatch):
    from efferents.agents import orchestrator as orch
    sub = tmp_path / "sub"
    shutil.copytree(SMOKE, sub, ignore=shutil.ignore_patterns("lab", "__pycache__"))
    (sub / "lab").mkdir()
    lab_mod.set_config(LabConfig.from_submission(sub))
    monkeypatch.delenv('EFFERENTS_NETWORK_URL', raising=False)
    monkeypatch.delenv('EFFERENTS_NETWORK_TOKEN', raising=False)
    monkeypatch.setattr(orch, 'notify_all', lambda **kw: None)
    o = orch.Orchestrator(lab_dir=sub / 'lab', context_dir=sub / 'context', dry_run=True,
                          submission_dir=sub)
    events = []
    class Reporter:
        def stop(self): events.append('worker stopped')
    class Client:
        def start_liveness(self, _): return Reporter()
    o.network = Client()
    monkeypatch.setattr(o, '_report_network_state', lambda *, status: events.append(status))
    o.run(max_iterations=0)
    assert events == ['worker stopped', 'stopped']

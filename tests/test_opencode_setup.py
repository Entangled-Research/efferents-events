"""The event's OpenCode provider must preserve other providers and hide secrets."""

import json
import stat

from efferents.cluster.opencode_setup import configure


def test_configure_opencode_uses_event_proxy_and_preserves_existing_config(tmp_path):
    event_path = tmp_path / ".event-config.json"
    event_path.write_text(json.dumps({
        "hub_url": "https://example.test",
        "env": {"EFFERENTS_NETWORK_TOKEN": "participant-secret",
                "EFFERENTS_MODEL_CODER": "openai/gpt-5.6-sol"},
    }))
    directory = tmp_path / "opencode"
    directory.mkdir()
    original = {"$schema": "https://opencode.ai/config.json",
                "plugin": ["opencode-gemini-auth@latest"],
                "provider": {"google": {"models": {"gemini": {"name": "Gemini"}}}}}
    config_path = directory / "opencode.json"
    config_path.write_text(json.dumps(original))

    assert configure(event_path, opencode_dir=directory) == "efferents-event/gpt-5.6-sol"
    saved = json.loads(config_path.read_text())
    assert saved["plugin"] == original["plugin"]
    assert saved["provider"]["google"] == original["provider"]["google"]
    assert saved["provider"]["efferents-event"]["npm"] == "@ai-sdk/openai"
    assert saved["provider"]["efferents-event"]["options"]["baseURL"] == (
        "https://example.test/proxy/openai/v1")
    assert "participant-secret" not in config_path.read_text()
    assert json.loads((directory / "opencode.json.before-efferents").read_text()) == original
    token_path = directory / "efferents-event-token"
    assert token_path.read_text() == "participant-secret"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    configure(event_path, opencode_dir=directory)
    assert json.loads((directory / "opencode.json.before-efferents").read_text()) == original


def test_bootstrap_configures_both_models_without_model_calls(tmp_path, monkeypatch):
    import io
    from efferents.cluster.opencode_setup import bootstrap
    requests = []
    event = {"hub_url": "https://event.test", "env": {
        "EFFERENTS_NETWORK_TOKEN": "participant-secret",
        "EFFERENTS_MODEL_CODER": "openai/gpt-6.1-sol",
        "EFFERENTS_MODEL_ROUTER": "openai/gpt-6-luna"}}

    def fetch(request, timeout):
        requests.append(request)
        return io.BytesIO(json.dumps(event).encode())

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    directory = tmp_path / "opencode"
    assert bootstrap("https://event.test", "participant-secret", opencode_dir=directory) == (
        "efferents-event/gpt-6.1-sol", "efferents-event/gpt-6-luna")
    assert len(requests) == 1
    assert requests[0].full_url == "https://event.test/api/network/config"
    assert requests[0].get_header("Authorization") == "Bearer participant-secret"
    saved = json.loads((directory / "opencode.json").read_text())
    assert saved["small_model"] == "efferents-event/gpt-6-luna"
    assert set(saved["provider"]["efferents-event"]["models"]) == {"gpt-6.1-sol", "gpt-6-luna"}


def test_launch_selects_only_event_provider_before_first_prompt(tmp_path, monkeypatch):
    import os
    from efferents.cluster.opencode_setup import launch
    calls = []
    monkeypatch.setenv("EFFERENTS_EVENT_TOKEN", "private-token")
    monkeypatch.setattr("shutil.which", lambda name: "/test/opencode")
    monkeypatch.setattr(os, "execvpe", lambda executable, args, env: calls.append((executable, args, env)))
    launch("https://event.test", "efferents-event/gpt-6.1-sol", "efferents-event/gpt-6-luna", opencode_dir=tmp_path, intake_session_id="approved-session")
    _, args, env = calls[0]
    assert args[1:3] == ["--model", "efferents-event/gpt-6.1-sol"]
    assert "private-token" not in " ".join(args)
    assert "EFFERENTS_EVENT_TOKEN" not in env
    settings = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert settings["enabled_providers"] == ["efferents-event"]
    assert settings["small_model"] == "efferents-event/gpt-6-luna"
    assert str(tmp_path / "efferents-event-token") in args[-1]
    assert "approved browser intake session approved-session" in args[-1]

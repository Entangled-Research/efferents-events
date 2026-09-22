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

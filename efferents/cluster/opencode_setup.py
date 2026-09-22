"""Configure OpenCode to use the event's Azure proxy without storing an Azure key."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _write_private(path: Path, content: str) -> None:
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(raw, path)
    finally:
        Path(raw).unlink(missing_ok=True)


def configure(config_path: Path, *, opencode_dir: Path | None = None) -> str:
    event = json.loads(config_path.read_text())
    env = event["env"]
    token = env["EFFERENTS_NETWORK_TOKEN"]
    model = env["EFFERENTS_MODEL_CODER"].removeprefix("openai/")
    if not token or model != "gpt-5.6-sol":
        raise ValueError("event config must contain a network token and the active Azure Sol model")
    hub_url = str(event["hub_url"]).rstrip("/")
    if not hub_url.startswith(("https://", "http://127.0.0.1:")):
        raise ValueError("event hub URL must use HTTPS")

    directory = (opencode_dir or Path.home() / ".config" / "opencode").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    token_path = directory / "efferents-event-token"
    config_file = directory / "opencode.json"
    if config_file.exists():
        settings = json.loads(config_file.read_text())
        if not isinstance(settings, dict):
            raise ValueError("OpenCode config must be a JSON object")
        backup = directory / "opencode.json.before-efferents"
        if not backup.exists():
            shutil.copy2(config_file, backup)
            backup.chmod(0o600)
    else:
        settings = {"$schema": "https://opencode.ai/config.json"}

    provider = settings.setdefault("provider", {})
    if not isinstance(provider, dict):
        raise ValueError("OpenCode provider config must be an object")
    _write_private(token_path, token)
    provider["efferents-event"] = {
        "npm": "@ai-sdk/openai",
        "name": "Efferents Event (Azure)",
        "options": {
            "baseURL": f"{hub_url}/proxy/openai/v1",
            "apiKey": f"{{file:{token_path}}}",
        },
        "models": {
            model: {
                "name": "GPT-5.6 Sol via Efferents Azure",
                "limit": {"context": 128000, "output": 32768},
            },
        },
    }
    settings["model"] = f"efferents-event/{model}"
    _write_private(config_file, json.dumps(settings, indent=2) + "\n")
    return settings["model"]


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m efferents.cluster.opencode_setup .event-config.json",
              file=sys.stderr)
        return 2
    try:
        model = configure(Path(args[0]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"OpenCode setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"OpenCode default set to {model}. Select it with /models in an existing session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Configure OpenCode to use the event's Azure proxy without storing an Azure key."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
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
    return configure_event(event, opencode_dir=opencode_dir)


def configure_event(event: dict, *, opencode_dir: Path | None = None) -> str:
    env = event["env"]
    token = env["EFFERENTS_NETWORK_TOKEN"]
    model = env["EFFERENTS_MODEL_CODER"].removeprefix("openai/")
    if not token or model not in {"gpt-5.6-sol", "gpt-6.1-sol"}:
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
                "name": f"{model.upper()} via Efferents Azure",
                "limit": {"context": 128000, "output": 32768},
            },
        },
    }
    small_model = env.get("EFFERENTS_MODEL_ROUTER", "openai/gpt-6-luna").removeprefix("openai/")
    if small_model != "gpt-6-luna":
        raise ValueError("event lightweight model must be GPT-6 Luna")
    provider["efferents-event"]["models"][small_model] = {
        "name": "Luna via Efferents Azure",
        "limit": {"context": 128000, "output": 32768},
    }
    settings["small_model"] = f"efferents-event/{small_model}"
    settings["model"] = f"efferents-event/{model}"
    _write_private(config_file, json.dumps(settings, indent=2) + "\n")
    return settings["model"]


def bootstrap(hub_url: str, token: str, *, opencode_dir: Path | None = None) -> tuple[str, str]:
    """Fetch config and configure a harness without making any model request."""
    hub_url = hub_url.rstrip("/")
    if not hub_url.startswith(("https://", "http://127.0.0.1:")) or not token:
        raise ValueError("Use an HTTPS event URL and a participant network token")
    request = urllib.request.Request(hub_url + "/api/network/config",
                                     headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=30) as response:
        event = json.load(response)
    if event.get("hub_url", "").rstrip("/") != hub_url:
        raise ValueError("Event configuration returned an unexpected hub URL")
    model = configure_event(event, opencode_dir=opencode_dir)
    small_model = "efferents-event/gpt-6-luna"
    return model, small_model


def launch(hub_url: str, model: str, small_model: str, *, opencode_dir: Path | None = None) -> None:
    executable = shutil.which("opencode")
    if not executable:
        raise ValueError("OpenCode is not installed. Install it from https://opencode.ai then run this setup again; no model credits have been used.")
    directory = (opencode_dir or Path.home() / ".config" / "opencode").resolve()
    prompt = (f"Read {hub_url.rstrip('/')}/intake.md and follow it. "
              f"My private event network token is in {directory / 'efferents-event-token'}; "
              "read it from that file instead of asking me to paste it. Keep it private and out of Git. "
              "Use the event's prepared starters and ask which scientific objective I want if needed.")
    environment = dict(os.environ)
    environment.pop("EFFERENTS_EVENT_TOKEN", None)
    # Override project defaults for this new session; do not expose personal providers.
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps({
        "model": model, "small_model": small_model,
        "enabled_providers": ["efferents-event"],
    })
    os.execvpe(executable, [executable, "--model", model, "--agent", "build", "--prompt", prompt], environment)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Connect OpenCode to organizer-funded event models.")
    parser.add_argument("config", nargs="?")
    parser.add_argument("--hub")
    parser.add_argument("--launch", action="store_true")
    options = parser.parse_args(args)
    try:
        if options.hub:
            model, small_model = bootstrap(options.hub, os.environ.get("EFFERENTS_EVENT_TOKEN", ""))
        elif options.config and not options.launch:
            model = configure(Path(options.config))
            small_model = "efferents-event/gpt-6-luna"
        else:
            parser.error("provide a config file or --hub URL")
        print("Event models configured: Sol for research and coding, Luna for lightweight tasks. "
              "Both use your shared event allowance.", flush=True)
        if options.launch:
            launch(options.hub, model, small_model)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"OpenCode setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

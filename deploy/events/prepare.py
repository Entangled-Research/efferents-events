"""Prepare an empty, paused event; never copy identities or billing state."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets

import yaml

from efferents.cluster.config import init_cluster, load_cluster_config, set_control_flag


def prepare(destination: Path, name: str, public_url: str) -> None:
    # Exclusive creation prevents accidentally resetting a previous event.
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = destination / "cluster"
    init_cluster(root)
    config = yaml.safe_load((root / "cluster.yaml").read_text())
    config.update(name=name, public_url=public_url, join_code=secrets.token_urlsafe(18))
    config["labs"]["hosted"] = False
    (root / "cluster.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    cfg = load_cluster_config(root)
    for flag in ("frozen", "pause_all", "stop_starts"):
        set_control_flag(cfg.paths, flag, "New event: configure credentials and budgets before rehearsal")
    # Compose credentials stay outside the state volume; no provider key is generated.
    env = destination / "hub.env"
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("# Set a new event-specific provider key before rehearsal.\n")
        out.write("OPENAI_API_KEY=\nEFFERENTS_API_BASE=\nEFFERENTS_AZURE_OPENAI_ENDPOINT=\n")
        out.write(f"EFFERENTS_ADMIN_TOKEN={secrets.token_urlsafe(32)}\n")
    print(f"Prepared paused event at {destination}; configure cluster/cluster.yaml and hub.env.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--public-url", required=True)
    args = parser.parse_args()
    prepare(args.destination.resolve(), args.name, args.public_url)

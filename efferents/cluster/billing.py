"""Operator-only, evidence-backed corrections to append-only proxy ledgers."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os

from efferents.agents.budget import CallUsage, cost_usd
from efferents.cluster.budget import coordinator
from efferents.cluster.config import write_event


def record_sha256(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _same_call(original: dict, other: dict) -> bool:
    if {k: v for k, v in original.items() if k != "ts"} != {k: v for k, v in other.items() if k != "ts"}:
        return False
    return abs((datetime.fromisoformat(original["ts"]) - datetime.fromisoformat(other["ts"])).total_seconds()) <= 2


def _append(path, record):
    with path.open("a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_ledger(path):
    text = path.read_text()
    if text and not text.endswith("\n"):
        raise ValueError("Billing ledger has an incomplete tail; inspect before correction")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Billing ledger contains an invalid record")
    return rows


def credit_cached_input(cfg, *, owner_id: str, original_sha256: str,
                        usage_record: dict, evidence: dict, apply: bool = False) -> dict:
    """Credit verified Chat cache overcharges; default is a no-write preview.

    Evidence must come from the participant's retained provider-usage ledger.
    Never infer cached tokens from similar prompts or unmatched model requests.
    The operator runs this against the hub's existing cluster configuration.
    """
    if not owner_id.isalnum():
        raise ValueError("Invalid owner identity")
    if (not evidence.get("source") or not evidence.get("file_sha256")
            or evidence.get("record_sha256") != record_sha256(usage_record)):
        raise ValueError("Retained usage proof and its hashes are required")
    owner_path = cfg.paths.root / "proxy" / owner_id / "budget.jsonl"
    global_path = cfg.paths.root / "proxy" / "budget.jsonl"
    with coordinator(cfg)._transaction():
        ledgers = {path: _read_ledger(path) for path in (owner_path, global_path)}
        originals = [row for row in ledgers[owner_path] if record_sha256(row) == original_sha256]
        if len(originals) != 1:
            raise ValueError("Original owner billing row must match exactly once")
        original = originals[0]
        if (original.get("agent") != "proxy" or str(original.get("notes", "")).split(" ", 1)[0] != f"owner={owner_id}"
                or original.get("cache_read_input_tokens", 0) or original.get("cache_creation_input_tokens", 0)
                or original.get("extra_cost_usd", 0)):
            raise ValueError("Only an original uncached proxy charge is eligible")
        global_matches = [row for row in ledgers[global_path] if _same_call(original, row)]
        if len(global_matches) != 1:
            raise ValueError("Original event-wide billing row must match exactly once")
        fields = ("input_tokens", "output_tokens", "cache_read_input_tokens")
        if any(type(usage_record.get(key)) is not int or usage_record[key] < 0 for key in fields):
            raise ValueError("Usage proof requires nonnegative integer token counts")
        cached = usage_record["cache_read_input_tokens"]
        if (cached <= 0 or usage_record.get("model") != original.get("model")
                or not str(original["model"]).startswith("openai/")
                or usage_record.get("cache_creation_input_tokens", 0) or usage_record.get("extra_cost_usd", 0)
                or usage_record["input_tokens"] + cached != original["input_tokens"]
                or usage_record["output_tokens"] != original["output_tokens"]
                or abs((datetime.fromisoformat(original["ts"]) - datetime.fromisoformat(usage_record["ts"])).total_seconds()) > 5):
            raise ValueError("Usage proof does not identify this exact cached call")
        candidates = [row for row in ledgers[owner_path]
                      if row.get("agent") == "proxy" and row.get("model") == original["model"]
                      and row.get("input_tokens") == original["input_tokens"]
                      and row.get("output_tokens") == original["output_tokens"]
                      and not row.get("cache_read_input_tokens")
                      and abs((datetime.fromisoformat(row["ts"]) - datetime.fromisoformat(usage_record["ts"])).total_seconds()) <= 5]
        if len(candidates) != 1:
            raise ValueError("Usage proof matches multiple original calls")
        for row in ledgers[global_path]:
            if (row.get("agent") == "billing_adjustment"
                    and row.get("evidence", {}).get("record_sha256") == evidence["record_sha256"]
                    and row.get("original_sha256") != original_sha256):
                raise ValueError("This retained usage proof already corrected another call")
        old_cost = cost_usd(original["model"], CallUsage(original["input_tokens"], original["output_tokens"]))
        corrected = cost_usd(original["model"], CallUsage(usage_record["input_tokens"], usage_record["output_tokens"],
                                                        cache_read_input_tokens=cached))
        if (not math.isclose(old_cost, original["cost_usd"], abs_tol=1e-10)
                or not math.isclose(corrected, usage_record["cost_usd"], abs_tol=1e-10)
                or not 0 <= corrected < old_cost):
            raise ValueError("Historical prices do not match the retained usage proof")
        identifier = "proxy-cache-v1:" + hashlib.sha256(f"{owner_id}:{original_sha256}".encode()).hexdigest()
        amount = round(corrected - old_cost, 12)
        credit = {"ts": datetime.now(timezone.utc).isoformat(), "agent": "billing_adjustment",
                  "model": original["model"], "input_tokens": 0, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                  "token_cost_usd": amount, "extra_cost_usd": 0.0, "cost_usd": amount,
                  "notes": f"owner={owner_id} verified Chat Completions cache correction",
                  "adjustment_id": identifier, "original_sha256": original_sha256,
                  "global_original_sha256": record_sha256(global_matches[0]),
                  "verified_cached_tokens": cached, "corrected_cost_usd": corrected,
                  "evidence": evidence}
        pending = []
        for path, rows in ledgers.items():
            existing = [row for row in rows if row.get("adjustment_id") == identifier]
            if existing:
                if len(existing) != 1 or existing[0].get("evidence", {}).get("record_sha256") != evidence["record_sha256"]:
                    raise ValueError("Existing adjustment conflicts with this correction")
                credit["evidence"] = existing[0]["evidence"]
                def compare(row):
                    return {k: v for k, v in row.items() if k != "ts"}
                if compare(existing[0]) != compare(credit):
                    raise ValueError("Existing adjustment conflicts with this correction")
                credit = existing[0]  # reuse the exact durable record on partial retry
            else:
                pending.append(path)
        if apply:
            for path in pending:
                _append(path, credit)
            if pending:
                write_event(cfg.paths, "proxy_cache_credit", owner_id=owner_id, adjustment_id=identifier,
                            original_sha256=original_sha256, credit_usd=-amount)
        return {"adjustment_id": identifier, "owner_id": owner_id, "credit_usd": -amount,
                "cached_tokens": cached, "status": "applied" if apply and pending else
                ("preview" if pending else "already_applied"), "ledger_writes": len(pending)}


def main():
    import argparse
    from pathlib import Path
    from efferents.cluster.config import load_cluster_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cluster_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="Append verified credits; default previews")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("version") != 1:
        raise ValueError("Expected reconciliation manifest version 1")
    cfg = load_cluster_config(args.cluster_root)
    directory = args.manifest.parent.resolve()
    for item in manifest["credits"]:
        proof = item["evidence"]
        archive = (directory / proof["archive"]).resolve()
        if not archive.is_relative_to(directory):
            raise ValueError("Retained evidence must remain within the reconciliation directory")
        data = archive.read_bytes()
        if hashlib.sha256(data).hexdigest() != proof["file_sha256"]:
            raise ValueError("Retained usage archive hash mismatch")
        record = json.loads(data.splitlines()[proof["line"] - 1])
        if record != item["usage_record"]:
            raise ValueError("Retained usage archive does not contain the asserted record")
        credit_cached_input(cfg, **item)  # validate the complete batch before any writes
    for item in manifest["credits"]:
        print(json.dumps(credit_cached_input(cfg, **item, apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()

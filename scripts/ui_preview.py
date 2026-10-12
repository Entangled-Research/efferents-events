"""Local, no-model UI rehearsal: serve real dashboard assets with synthetic API data."""
import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

NOW = datetime.now(timezone.utc).isoformat()
JOURNAL = "Generative Modelling"
SPECS = [
    ("sample-efficiency", "Sample efficiency", "Ada", "running", 2.46, 12, 18.7, "accepted"),
    ("noise-schedules", "Noise schedules", "Ada", "paused", 1.38, 8, 21.4, "rejected"),
    ("representation", "Representation", "Lin", "running", 1.92, 10, 19.2, "pending"),
    ("evaluation", "Evaluation", "Sam", "stopped", .74, 4, None, "pending"),
]

def idea(lab_id, index=0):
    names = {"sample-efficiency": ["Adaptive sampling", "Uniform baseline"],
             "noise-schedules": ["Learned schedule", "Cosine control"],
             "representation": ["Latent compression", "Pixel baseline"],
             "evaluation": ["Coverage check", "Seed stability"]}
    return {"id": "primary" if index == 0 else "control", "name": names[lab_id][index],
            "focus": "Compare a bounded intervention against a matched baseline across three seeds.",
            "verdict": "undecided", "eval_suite": {"rationale": "Matched compute, fixed holdout and three seeds."}}

LABS = [{"lab_id": lid, "display_name": name, "owner_name": owner,
         "domain": "machine learning", "journal": JOURNAL, "status": status,
         "remote": True, "mine": owner == "Ada", "selected": False,
         "source": "participant laptop", "last_activity": NOW, "heartbeat_ts": NOW,
         "received_at": NOW, "budget": {"spent": spend},
         "hypothesis": {"question": "Can a matched-compute intervention reduce held-out error?"},
         "ideas": [idea(lid), idea(lid, 1)],
         "headline": {"column": "heldout_error", "direction": "min", "observations": runs,
                      "best": best, "latest": best},
         "review_board": {"status": review, "campaign_id": "campaign-01",
                          "scores": {"critical": 6, "neutral": 7, "optimistic": 8} if review == "accepted" else
                                    {"critical": 2, "neutral": 4, "optimistic": 5} if review == "rejected" else {}}}
        for lid, name, owner, status, spend, runs, best, review in SPECS]
FINDINGS = [{"id": "simulated-paper-01", "kind": "publication", "publication_status": "accepted",
             "lab_id": "sample-efficiency", "campaign_id": "campaign-01", "journal": JOURNAL,
             "domain": "machine learning", "title": "Adaptive sampling under matched compute",
             "body": "A simulated accepted paper comparing adaptive sampling with a fixed baseline.",
             "review_scores": {"critical": 6, "neutral": 7, "optimistic": 8}, "ts": NOW,
             "manuscript": "# Adaptive sampling under matched compute\n\nSIMULATED PREVIEW RECORD.\n\n## Method\nThree paired seeds; fixed holdout and equal compute.\n\n## Results\nPreview values only; no real scientific conclusion.\n\n## Limitations\nSmall synthetic rehearsal. Replication remains required."}]
PORTFOLIO = {"labs": LABS, "findings": FINDINGS, "observations": [
    {"finding_id": "simulated-paper-01", "source": "sample-efficiency", "target": "representation", "ts": NOW}],
    "edges": [], "journals": [], "journal_uses": [], "event_network": None}

def control(lab=None):
    payload = {"mode": "cluster", "connected": bool(lab), "csrf_token": "local-preview",
               "cluster": {"joined": True, "name": "Autoresearch: Agents x Science", "owner": {"name": "Ada"},
                           "my_labs": ["sample-efficiency", "noise-schedules"], "hosted_labs": False,
                           "frozen": False, "owner_budget": {"spent_usd": 3.84, "cap_usd": 10,
                                                                "reserved_usd": .36, "remaining_usd": 5.8}}}
    if lab:
        payload.update({**lab, "owner_paused": lab["status"] == "paused", "has_api_key": True,
                        "steering": [], "contract": {"valid": True}, "source": "participant laptop"})
    return payload

def suite(lab, iid):
    private = not lab["mine"]
    best = lab["headline"]["best"] or 18.7
    values = [round(best + delta, 1) for delta in [0, .6, 1.4, 2.3, 3.7, 5.5]]
    rows = [{"run_id": f"run-{6-i:03d}", "value": v, "eligible": True,
             "status": "succeeded", "ts": NOW, "started_at": NOW, "cost_usd": .19, "metrics": {"heldout_error": v}}
            for i, v in enumerate(values)]
    return {"detail_unavailable": private, "hypothesis": {
        "question": idea(lab["lab_id"], iid == "control")["name"],
        "claim": "At matched compute, the intervention reduces held-out error by at least 10%.",
        "falsifier": "Reject if paired error reduction is below 10% across three seeds.", "student": iid},
        "suite": {"title": "Matched-compute evaluation", "message": "Simulated preview · no scientific verdict",
                  "rationale": "Fixed holdout, equal compute, three paired seeds.", "samples": [],
                  "graphs": [{"title": "Held-out error", "series": [{"column": "heldout_error", "points":
                    [{"run_id": r["run_id"], "value": r["value"]} for r in reversed(rows)]}]}] if not private else []},
        "runs": {"runs": rows, "series": list(reversed(rows)), "history": {"total": 6, "best": best},
                 "headline": {"column": "heldout_error", "direction": "min"}},
        "evidence": {"records": [], "panels": []},
        "verdict": {"verdict": "undecided", "line": "Undecided · preview evidence only", "n_runs": 6,
                    "falsifiers": [], "buckets": [], "columns": [], "axes": []}}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/"):
            if path == "/api/control": data = control()
            elif path == "/api/labs": data = PORTFOLIO
            elif path.startswith("/api/labs/"):
                parts = path.split("/")
                lab = next((x for x in LABS if x["lab_id"] == parts[3]), None)
                if not lab: return self.send_json({"error": "Unknown preview lab"}, 404)
                data = suite(lab, parts[5]) if len(parts) > 5 and parts[4] == "ideas" else control(lab)
            elif path == "/api/diagnostics": data = {"summary": "Local simulated preview; no models or live hub connected.", "checks": []}
            elif path == "/api/intake/sessions": data = []
            else: data = {}
            return self.send_json(data)
        target = self.server.assets / (path.removeprefix("/static/") if path.startswith("/static/") else "dashboard.html")
        if target.parent != self.server.assets or not target.exists():
            return self.send_error(404)
        content = target.read_bytes()
        if target.suffix == ".html":
            badge = '<div style="position:fixed;bottom:8px;right:8px;z-index:9999;padding:6px 10px;background:#172a38;color:#fff;font:11px monospace;pointer-events:none">SIMULATED PREVIEW · NO MODEL CALLS</div>'
            content = content.replace(b"</body>", badge.encode() + b"</body>")
        self.send_response(200)
        self.send_header("Content-Type", {".html": "text/html", ".css": "text/css", ".js": "application/javascript"}.get(target.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        self.send_json({"error": "Preview is read-only. Research and account actions are disabled."}, 403)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *_): pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8840)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.assets = args.repo.resolve() / "efferents/dashboard/static"
    print(f"http://127.0.0.1:{args.port}/#network", flush=True)
    server.serve_forever()

"""Synthetic UI scaling snapshots based on main's starter.md, not research results."""
import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

NOW = datetime.now(timezone.utc).isoformat()
THEMES = [
    {"id": "sample-efficient-diffusion", "title": "Sample-Efficient Diffusion", "journal": "Generative Modelling",
     "claim": "Maybe we can get diffusion models to learn from much less data.", "metric": "heldout_fid", "best": 18.7, "direction": "min",
     "ideas": ["Data efficiency", "Matched-compute control"],
     "siblings": ["Diffusion curriculum", "Augmentation policy", "Latent transfer", "Distillation", "Noise schedules", "Data selection", "Small-model diffusion", "Patch sampling", "Few-shot priors", "Consistency training", "Adaptive batches"]},
    {"id": "uncertainty-hallucination", "title": "Uncertainty and Hallucination", "journal": "Reliability & Evaluation",
     "claim": "Maybe transformers hallucinate more when they're less certain, and we can use this to flag potential hallucination.",
     "metric": "detector_auroc", "best": .78, "direction": "max", "ideas": ["Uncertainty correlation", "Hallucination detection"],
     "siblings": ["Confidence calibration", "Selective answering", "Semantic uncertainty", "Claim verification", "Abstention policy", "Shift detection", "Evidence retrieval"]},
    {"id": "intermediate-visual-reasoning", "title": "Intermediate Visual Reasoning", "journal": "Spatial Reasoning",
     "claim": "Maybe letting models draw intermediate steps helps them understand spatial problems better.",
     "metric": "spatial_accuracy", "best": .72, "direction": "max", "ideas": ["Drawing intermediate steps", "Text-only control"],
     "siblings": ["Sketch planning", "Diagram grounding", "Geometry verification", "Visual scratchpads", "Scene decomposition", "Rotation reasoning", "Spatial composition"]},
]


def build_snapshot(count):
    labs, findings, receipts = [], [], []
    populations = [1, 1, 1] if count == 3 else [count // 2, count // 3, count - count // 2 - count // 3]
    for topic_index, topic in enumerate(THEMES):
        topic_labs = []
        per_theme = populations[topic_index]
        for sibling in range(per_theme):
            lid = topic["id"] if sibling == 0 else f'{topic["id"]}-{sibling + 1}'
            title = topic["title"] if sibling == 0 else topic["siblings"][sibling - 1]
            starter = count == 3
            review = "awaiting paper" if starter else ["accepted", "pending", "rejected", "pending"][sibling % 4]
            measured = not starter and sibling % 4 != 3
            patterns = ([3, 5, 2, 4, 1, 5], [2, 1, 3, 2], [1, 2, 1, 2])
            idea_count = patterns[topic_index][sibling % len(patterns[topic_index])]
            names = list(topic["ideas"]) if sibling == 0 else [title, "Baseline control"]
            names = (names + ["Seed stability", "Ablation study", "Held-out validation"])[:idea_count]
            ideas = [{"id": "primary" if index == 0 else f"idea-{index + 1}", "name": name,
                      "focus": topic["claim"], "verdict": "undecided",
                      "eval_suite": {"rationale": "Paired seeds, held-out data, matched compute."}} for index, name in enumerate(names)]
            best = round(topic["best"] + (1 if topic["direction"] == "min" else -1) * sibling * (.7 if topic["best"] > 1 else .015), 3)
            lab = {"lab_id": lid, "display_name": title, "owner_name": "Ada" if sibling == 0 else f"Participant {len(labs) + 1:02d}",
                   "domain": "machine learning", "journal": topic["journal"],
                   "status": "stopped" if starter else ["running", "running", "paused", "stopped"][sibling % 4],
                   "remote": True, "mine": sibling == 0, "selected": False, "source": "participant laptop",
                   "last_activity": NOW, "heartbeat_ts": NOW, "received_at": NOW,
                   "budget": {"spent": 0 if starter else 1.28 if sibling == 0 else round(.42 + sibling * .31, 2)},
                   "hypothesis": {"question": topic["claim"]}, "ideas": ideas,
                   "headline": {"column": topic["metric"], "direction": topic["direction"], "observations": 0 if starter else 6 + sibling * 2,
                                "best": best if measured else None, "latest": best if measured else None},
                   "review_board": {"status": review, "campaign_id": "simulated-campaign-01",
                                    "scores": {"critical": 6, "neutral": 7, "optimistic": 8} if review == "accepted" else
                                              {"critical": 2, "neutral": 4, "optimistic": 5} if review == "rejected" else {}}}
            labs.append(lab); topic_labs.append(lab)
            if review == "accepted":
                findings.append({"id": f"simulated-paper-{lid}", "kind": "publication", "publication_status": "accepted",
                                 "lab_id": lid, "campaign_id": "simulated-campaign-01", "journal": topic["journal"],
                                 "domain": "machine learning", "title": f"{title}: simulated matched-control study",
                                 "body": "Simulated preview publication; no scientific conclusion.", "review_scores": lab["review_board"]["scores"],
                                 "published_at": NOW, "ts": NOW,
                                 "manuscript": f"# {title}\n\nSIMULATED PREVIEW RECORD.\n\n## Starting hypothesis\n{topic['claim']}\n\n## Method\nHeld-out data and matched controls.\n\n## Results\nPreview values only. No real research was run.\n\n## Limitations\nReplication remains required."})
        if not starter:
            # Several distinct accepted papers have been read by the same neighbour.
            # This is synthetic recorded history, not a new exchange each refresh.
            repeats = [6, 2, 1][topic_index]
            original = next(paper for paper in findings if paper["lab_id"] == topic_labs[0]["lab_id"])
            for history in range(1, repeats):
                paper = {**original, "id": f"{original['id']}-history-{history}", "campaign_id": f"simulated-history-{history}",
                         "title": f"{topic_labs[0]['display_name']}: simulated study {history + 1}"}
                findings.append(paper)
                receipts.append({"finding_id": paper["id"], "source": paper["lab_id"], "target": topic_labs[1]["lab_id"], "ts": NOW})
            receipts.append({"finding_id": f"simulated-paper-{topic_labs[0]['lab_id']}", "source": topic_labs[0]["lab_id"],
                             "target": topic_labs[1]["lab_id"], "ts": NOW})
    if count > 3:
        receipts.append({"finding_id": f"simulated-paper-{THEMES[0]['id']}", "source": THEMES[0]["id"],
                         "target": f"{THEMES[2]['id']}-2", "ts": NOW})
    return {"labs": labs, "findings": findings, "observations": receipts, "edges": [], "journals": [], "journal_uses": [], "event_network": None}


SNAPSHOTS = {count: build_snapshot(count) for count in (3, 12, 24)}


def control(snapshot, lab=None):
    spent = sum(lab["budget"]["spent"] for lab in snapshot["labs"] if lab["mine"])
    reserved = .36 if spent else 0
    payload = {"mode": "cluster", "connected": bool(lab), "csrf_token": "local-preview",
               "cluster": {"joined": True, "name": "Autoresearch: Agents x Science", "owner": {"name": "Ada"},
                           "my_labs": [lab["lab_id"] for lab in snapshot["labs"] if lab["mine"]], "hosted_labs": False, "frozen": False,
                           "owner_budget": {"spent_usd": spent, "cap_usd": 10, "reserved_usd": reserved, "remaining_usd": 10 - spent - reserved}}}
    if lab:
        payload.update({**lab, "owner_paused": lab["status"] == "paused", "has_api_key": True,
                        "steering": [], "contract": {"valid": True}, "source": "participant laptop"})
    return payload


def suite(lab, iid):
    private = not lab["mine"]
    best = lab["headline"]["best"]
    measured = best is not None
    sign = 1 if lab["headline"]["direction"] == "min" else -1
    span = 5 if best and best > 1 else .15
    values = [round(best + sign * span * i / 5, 3) for i in range(6)] if measured else []
    rows = [{"run_id": f"run-{6-i:03d}", "value": value, "eligible": True, "status": "succeeded", "ts": NOW, "started_at": NOW} for i, value in enumerate(values)]
    idea = next((idea for idea in lab["ideas"] if idea["id"] == iid), lab["ideas"][0])
    return {"detail_unavailable": private,
            "hypothesis": {"question": idea["name"], "claim": lab["hypothesis"]["question"], "falsifier": "Declare a quantitative falsifier before running experiments.", "student": iid},
            "suite": {"title": idea["name"], "message": "Simulated preview · no scientific verdict", "rationale": idea["focus"], "samples": [],
                      "graphs": [{"title": lab["headline"]["column"], "series": [{"column": lab["headline"]["column"], "points": list(reversed(rows))}]}] if measured and not private else []},
            "runs": {"runs": rows, "series": list(reversed(rows)), "history": {"total": len(rows), "best": best}, "headline": lab["headline"]},
            "evidence": {"records": [], "panels": []},
            "verdict": {"verdict": "undecided", "line": "Undecided · preview only", "n_runs": len(rows), "falsifiers": [], "buckets": [], "columns": [], "axes": []}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        count = parse_qs(parsed.query).get("preview_labs" if path.startswith("/api/") else "labs", ["12"])[0]
        count = int(count) if count in {"3", "12", "24"} else 12
        snapshot = SNAPSHOTS[count]
        if path.startswith("/api/"):
            if path == "/api/control": data = control(snapshot)
            elif path == "/api/labs": data = snapshot
            elif path.startswith("/api/labs/"):
                parts = path.split("/")
                lab = next((lab for lab in snapshot["labs"] if lab["lab_id"] == parts[3]), None)
                if not lab: return self.send_json({"error": "Unknown preview lab"}, 404)
                data = suite(lab, parts[5]) if len(parts) > 5 and parts[4] == "ideas" else control(snapshot, lab)
            elif path == "/api/diagnostics": data = {"summary": "Read-only simulated preview.", "checks": []}
            elif path == "/api/intake/sessions": data = []
            else: data = {}
            return self.send_json(data)
        target = self.server.assets / (path.removeprefix("/static/") if path.startswith("/static/") else "dashboard.html")
        if target.parent != self.server.assets or not target.exists(): return self.send_error(404)
        content = target.read_bytes()
        if target.suffix == ".html":
            script = f'''<script>const previewSize={count};const actualFetch=window.fetch.bind(window);window.fetch=(input,init)=>{{if(typeof input==='string'&&input.startsWith('/api/')){{const url=new URL(input,location.origin);url.searchParams.set('preview_labs',previewSize);input=url.toString();}}return actualFetch(input,init);}};</script>'''
            content = content.replace(b"</head>", script.encode() + b"</head>")
            links = ' '.join(f'<a href="/?labs={size}#network" style="color:{"#c1efdb" if size == count else "#fff"};text-decoration:{"underline" if size == count else "none"}">{size}</a>' for size in (3, 12, 24))
            badge = f'<aside aria-label="Preview scale" style="position:fixed;bottom:8px;right:8px;z-index:9999;padding:7px 10px;background:#172a38;color:#fff;font:11px monospace">PREVIEW LABS · {links} &nbsp; SIMULATED · NO CALLS</aside>'
            content = content.replace(b"</body>", badge.encode() + b"</body>")
        self.send_response(200)
        self.send_header("Content-Type", {".html": "text/html", ".css": "text/css", ".js": "application/javascript"}.get(target.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(content)

    def do_POST(self):
        self.send_json({"error": "Preview is read-only. Research and account actions are disabled."}, 403)

    def send_json(self, data, status=200):
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(json.dumps(data).encode())

    def log_message(self, *_): pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--repo", required=True, type=Path); parser.add_argument("--port", type=int, default=8842)
    args = parser.parse_args(); server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.assets = args.repo.resolve() / "efferents/dashboard/static"
    print(f"http://127.0.0.1:{args.port}/?labs=12#network", flush=True)
    server.serve_forever()

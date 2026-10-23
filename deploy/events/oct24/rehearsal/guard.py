"""Local, fail-closed rehearsal proxy: one reserved spend cap across lab processes.

Run with the Events virtualenv. Credentials are read from a private .env, never
written to logs. This operator tool forwards non-streaming participant requests
through the real event proxy; it never simulates a model response.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
import uuid

from efferents.agents.budget import CallUsage, cost_usd, estimate_call_cost_usd
from efferents.envfile import load_dotenv


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Guard:
    def __init__(self, root: Path, hub: str, token: str, cap: float):
        self.root, self.hub, self.token, self.cap = root, hub.rstrip('/'), token, cap
        self.lock = threading.RLock()
        self.spent = 0.0
        self.pending = {}
        self.stopped = False
        if (root / 'guard.jsonl').exists():
            for line in (root / 'guard.jsonl').read_text().splitlines():
                row = json.loads(line)
                if row['event'] == 'reserve':
                    self.pending[row['id']] = row['estimate']
                elif row['event'] == 'settle':
                    self.spent += row['cost']
                    self.pending.pop(row['id'], None)

    def log(self, event, **fields):
        with (self.root / 'guard.jsonl').open('a') as stream:
            stream.write(json.dumps({'ts': stamp(), 'event': event, **fields}) + '\n')

    def state(self):
        with self.lock:
            return {'spent': self.spent, 'held': sum(self.pending.values()), 'cap': self.cap,
                    'pending': len(self.pending), 'stopped': self.stopped,
                    'remaining': self.cap-self.spent-sum(self.pending.values())}

    def reserve(self, model, output, length, lab, image_tokens=0):
        estimate = estimate_call_cost_usd(model, output, max(1, length // 3) + image_tokens)
        with self.lock:
            if self.stopped or (self.root / 'STOP').exists() or self.spent+sum(self.pending.values())+estimate > self.cap:
                raise ValueError('Rehearsal aggregate cap reached or owner stopped the run')
            identifier = uuid.uuid4().hex
            self.pending[identifier] = estimate
            self.log('reserve', id=identifier, model=model, estimate=estimate, lab=lab)
            return identifier

    def settle(self, identifier, model, payload, status, lab):
        usage = payload.get('usage') or {}
        if status >= 500:
            self.log('unresolved', id=identifier, lab=lab, status=status)
            return
        if status >= 400:
            cost = 0.0
        elif usage:
            total = usage.get('input_tokens', usage.get('prompt_tokens', 0))
            cached = (usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
            cost = cost_usd(model, CallUsage(total-cached, usage.get('output_tokens', usage.get('completion_tokens', 0)), cache_read_input_tokens=cached))
        else:
            # Unknown billing stays reserved; uncertainty must not create credit.
            self.log('unresolved', id=identifier, lab=lab, status=status)
            return
        with self.lock:
            estimate = self.pending.pop(identifier)
            self.spent += cost
            if cost > estimate:
                self.stopped = True
            self.log('settle', id=identifier, lab=lab, status=status, cost=cost,
                     model=model, usage=usage, estimate=estimate)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != '/status':
            return self.respond(404, {})
        self.respond(200, self.server.guard.state())

    def do_POST(self):
        guard = self.server.guard
        if self.headers.get('Authorization') != 'Bearer '+guard.token:
            return self.respond(401, {'error': {'message': 'Invalid rehearsal participant token'}})
        parts = self.path.split('/', 3)
        if len(parts) != 4 or parts[1] != 'lab':
            return self.respond(404, {})
        lab, path = parts[2], '/'+parts[3]
        if path not in ('/proxy/openai/v1/responses', '/proxy/openai/v1/chat/completions'):
            return self.respond(404, {})
        identifier = None
        try:
            body = self.rfile.read(int(self.headers['Content-Length']))
            request = json.loads(body)
            if request.get('stream'):
                raise ValueError('Rehearsal guard requires non-streaming requests')
            model = 'openai/'+request['model'].removeprefix('openai/')
            if model not in ('openai/gpt-6-luna', 'openai/gpt-6.1-sol'):
                raise ValueError('Unexpected rehearsal model')
            output = request.get('max_output_tokens') or request.get('max_completion_tokens') or request.get('max_tokens')
            if not isinstance(output, int) or output < 1:
                raise ValueError('A positive output limit is required')
            from efferents.cluster.proxy import image_input_tokens
            identifier = guard.reserve(model, output, len(body), lab, image_input_tokens(request))
            upstream = urllib.request.Request(guard.hub+path, data=body,
                         headers={'Authorization':'Bearer '+guard.token, 'Content-Type':'application/json'})
            try:
                response = urllib.request.urlopen(upstream, timeout=180)
                status, payload = response.status, json.load(response)
            except urllib.error.HTTPError as error:
                status = error.code
                payload = json.loads(error.read())
            guard.settle(identifier, model, payload, status, lab)
            self.respond(status, payload)
        except ValueError as error:
            self.respond(429 if identifier is None else 502, {'error':{'message':str(error), 'type':'rehearsal_limit'}})
        except Exception as error:
            # Preserve pending reservation: the upstream might have billed it.
            guard.log('transport_error', id=identifier, lab=lab, error=type(error).__name__)
            self.respond(502, {'error':{'message':'Rehearsal upstream request failed; reservation retained'}})


def main():
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--cap', type=float, default=29.0)
    args = parser.parse_args()
    if not 0 < args.cap <= 30:
        raise ValueError('Rehearsal cap must be within the authorized $30')
    args.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.run_dir, 0o700)
    load_dotenv(args.env)
    guard = Guard(args.run_dir, os.environ['EFFERENTS_NETWORK_URL'], os.environ['EFFERENTS_NETWORK_TOKEN'], args.cap)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.guard = guard
    (args.run_dir / 'guard-port').write_text(str(server.server_port))
    server.serve_forever()


if __name__ == '__main__':
    main()

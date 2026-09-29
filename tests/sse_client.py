"""Minimal SSE client helpers (stdlib only) to drive the backend for proofs."""

import json
import urllib.request

BASE = "http://localhost:8000"


def start_run(message, thread_id=None):
    body = json.dumps({"message": message, "thread_id": thread_id}).encode()
    req = urllib.request.Request(
        f"{BASE}/runs", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def cancel_run(run_id):
    req = urllib.request.Request(f"{BASE}/runs/{run_id}/cancel", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def stream(run_id, last_event_id=None, max_events=100000, on_event=None, timeout=120):
    """Yield (offset, envelope) from the SSE stream until run.finished."""
    headers = {}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    req = urllib.request.Request(f"{BASE}/runs/{run_id}/stream", headers=headers)
    out = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = ""
        n = 0
        for raw in r:
            buf += raw.decode("utf-8")
            while "\n\n" in buf:
                record, buf = buf.split("\n\n", 1)
                data = ""
                for line in record.split("\n"):
                    if line.startswith("data:"):
                        data += line[5:].strip()
                if not data:
                    continue
                env = json.loads(data)
                out.append(env)
                if on_event:
                    on_event(env)
                n += 1
                if env.get("type") == "run.finished" or n >= max_events:
                    return out
    return out

"""Data-access seam for threads (conversations) and thread<->run association.

Today this is JSON-file backed. Bucket B (B1) reimplements these function
*bodies* against Postgres — same signatures, same return shapes — so the API
endpoints and the frontend never change.

Canonical schema (the B1 target these shapes map onto 1:1):

    threads(
      thread_id  text PRIMARY KEY,
      title      text,                       -- writable (A1), not always derived
      created_at timestamptz,
      updated_at timestamptz,
      deleted_at timestamptz NULL,           -- soft delete/archive (A1)
      user_id    text NULL,                  -- Mandate 2
      org_id     text NULL
    )
    runs(
      run_id     text PRIMARY KEY,
      thread_id  text REFERENCES threads,
      workflow_id text, user_message text, status text,
      created_at timestamptz,
      user_id    text NULL, org_id text NULL
    )
    events(
      run_id text, event_offset int,         -- A2: column is event_offset;
      ts timestamptz, type text, payload jsonb,   -- `offset` is reserved in PG.
      user_id text NULL, org_id text NULL,        -- The v1 WIRE envelope keeps
      PRIMARY KEY (run_id, event_offset)          -- the field name `offset`.
    )

B1 changes ONLY: (1) these function bodies -> SQL; (2) events JSONL -> events
table (event_offset column); (3) add indexes runs(thread_id), threads(updated_at).
Nothing here that Postgres won't want.
"""

import contextlib
import json
import os
import re
from datetime import datetime, timezone

ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")
THREADS_FILE = os.path.join(ARTIFACT_BASE, ".thread_registry.json")

# thread_id -> {title, created_at, updated_at, deleted_at, user_id, org_id}
_threads: dict[str, dict] = {}
_loaded = False

_TS_TAIL_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save() -> None:
    os.makedirs(ARTIFACT_BASE, exist_ok=True)
    tmp = THREADS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_threads, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, THREADS_FILE)


def _readable(run_id: str, user_message: str) -> str:
    """A thread title: the first user message, else a de-slugified run_id."""
    if user_message:
        return user_message[:80]
    m = re.match(r"^(.*)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", run_id)
    slug = m.group(1) if m else run_id
    text = slug.replace("-", " ").strip()
    return (text[:1].upper() + text[1:]) if text else run_id


def _run_created_at(run_id: str, info: dict) -> str:
    if info.get("created_at"):
        return info["created_at"]
    m = _TS_TAIL_RE.search(run_id)  # slug_YYYY-MM-DD_HH-MM-SS
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"
    return ""


def load(runs: dict) -> None:
    """Load thread records. On first run of this code (no file yet), archive
    every pre-existing run's thread so the sidebar starts clean (A3). Reversible:
    deleted_at is a soft delete.
    """
    global _loaded
    if _loaded:
        return
    if os.path.isfile(THREADS_FILE):
        with contextlib.suppress(Exception):
            with open(THREADS_FILE, "r", encoding="utf-8") as f:
                _threads.update(json.load(f))
        _loaded = True
        return

    now = _now()
    by_thread: dict[str, list[tuple[str, dict]]] = {}
    for run_id, info in runs.items():
        tid = info.get("thread_id") or f"legacy-{run_id}"
        by_thread.setdefault(tid, []).append((run_id, info))
    for tid, items in by_thread.items():
        items.sort(key=lambda x: _run_created_at(x[0], x[1]))
        first_rid, first_info = items[0]
        _threads[tid] = {
            "title": _readable(first_rid, first_info.get("user_message", "")),
            "created_at": _run_created_at(*items[0]) or now,
            "updated_at": _run_created_at(*items[-1]) or now,
            "deleted_at": now,  # archived out of the default view
            "user_id": None,
            "org_id": None,
        }
    _save()
    _loaded = True


def ensure_thread(thread_id: str, first_user_message: str, run_id: str) -> None:
    """Create a thread record on the first message (A4: no empty threads)."""
    if thread_id in _threads:
        return
    now = _now()
    _threads[thread_id] = {
        "title": _readable(run_id, first_user_message),
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "user_id": None,
        "org_id": None,
    }
    _save()


def touch_thread(thread_id: str) -> None:
    t = _threads.get(thread_id)
    if t:
        t["updated_at"] = _now()
        _save()


def set_title(thread_id: str, title: str) -> None:
    """Writable title (A1) — rename endpoint not built yet, seam ready."""
    t = _threads.get(thread_id)
    if t:
        t["title"] = title
        _save()


def soft_delete(thread_id: str) -> None:
    """Archive/delete (A1) — endpoint not built yet, seam ready."""
    t = _threads.get(thread_id)
    if t:
        t["deleted_at"] = _now()
        _save()


def list_threads(runs: dict) -> list[dict]:
    """Non-deleted threads, newest updated_at first, with run counts."""
    counts: dict[str, int] = {}
    for info in runs.values():
        tid = info.get("thread_id")
        if tid:
            counts[tid] = counts.get(tid, 0) + 1
    out = [
        {
            "thread_id": tid,
            "title": t["title"],
            "created_at": t["created_at"],
            "updated_at": t["updated_at"],
            "run_count": counts.get(tid, 0),
        }
        for tid, t in _threads.items()
        if not t.get("deleted_at")  # A1 filter in the seam from day one
    ]
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def get_thread(thread_id: str, runs: dict) -> dict | None:
    t = _threads.get(thread_id)
    if not t or t.get("deleted_at"):
        return None
    thread_runs = [
        {"run_id": rid, "status": info.get("status", "unknown"),
         "created_at": _run_created_at(rid, info)}
        for rid, info in runs.items()
        if info.get("thread_id") == thread_id
    ]
    thread_runs.sort(key=lambda r: r["created_at"])
    return {
        "thread_id": thread_id,
        "title": t["title"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "runs": thread_runs,
    }

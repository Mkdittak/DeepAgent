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
    skills(                                  -- Agent Skills (agentskills.io)
      skill_id    text PRIMARY KEY,          -- uuid4.hex (C3: opaque); the
                                             -- deterministic "builtin-<name>"
                                             -- ids are enable-override rows
                                             -- for repo-shipped skills only
      name        text,                      -- spec-validated at install
      tier        text,                      -- 'built-in' | 'org' | 'user'
      description text,
      source      text,                      -- provenance: 'repo' | 'upload'
      trust_state text,                      -- 'trusted' | 'untrusted';
                                             -- untrusted rows are NEVER
                                             -- seeded into agent state
      enabled     boolean,
      body        text,                      -- full SKILL.md
      files       jsonb,                     -- {relative_path: content}
      created_at  timestamptz, updated_at timestamptz,
      deleted_at  timestamptz NULL,
      user_id     text NULL, org_id text NULL,
      UNIQUE (tier, name, user_id, org_id)
    )

B1 changes ONLY: (1) these function bodies -> SQL; (2) events JSONL -> events
table (event_offset column); (3) add indexes runs(thread_id), threads(updated_at).
Nothing here that Postgres won't want.
"""

import contextlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")
THREADS_FILE = os.path.join(ARTIFACT_BASE, ".thread_registry.json")
SKILLS_FILE = os.path.join(ARTIFACT_BASE, ".skill_registry.json")

# thread_id -> {title, created_at, updated_at, deleted_at, user_id, org_id}
_threads: dict[str, dict] = {}
_loaded = False

# skill_id -> row (see the skills schema in the module docstring). Org/user
# rows plus enable-override rows for built-ins; the worker reads this same
# JSON file (read-only) when seeding runs — see agent/skills.py.
_skills: dict[str, dict] = {}
_skills_loaded = False

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


def backfill_identity(runs: dict, user_id: str, org_id: str) -> dict[str, int]:
    """One-time stamp of pre-auth rows with the LEGACY identity (mirrors the
    A3 thread archive above). Any thread / run / org-or-user skill row whose
    user_id is null gets (user_id, org_id), so data created before
    AUTH_ENABLED lands in one claimable bucket instead of being invisible to
    every real tenant. Idempotent: rows already stamped are untouched.

    Built-in enable-override rows are deliberately left null — they are a
    project-wide toggle, not a tenant's data.

    `runs` is the caller's run registry (mutated in place, like load()); the
    caller persists it. Returns per-table counts of rows stamped.
    """
    _load_skills()
    counts = {"threads": 0, "runs": 0, "skills": 0}
    for t in _threads.values():
        if t.get("user_id") is None:
            t["user_id"], t["org_id"] = user_id, org_id
            counts["threads"] += 1
    for info in runs.values():
        if isinstance(info, dict) and info.get("user_id") is None:
            info["user_id"], info["org_id"] = user_id, org_id
            counts["runs"] += 1
    for row in _skills.values():
        if row.get("tier") in ("org", "user") and row.get("user_id") is None:
            row["user_id"], row["org_id"] = user_id, org_id
            counts["skills"] += 1
    if counts["threads"]:
        _save()
    if counts["skills"]:
        _save_skills()
    return counts


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


def set_title(thread_id: str, title: str) -> bool:
    """Writable title (A1). Returns False for unknown/deleted threads."""
    t = _threads.get(thread_id)
    if not t or t.get("deleted_at"):
        return False
    t["title"] = title
    t["updated_at"] = _now()
    _save()
    return True


def soft_delete(thread_id: str) -> bool:
    """Archive/delete (A1). Idempotent; returns False for unknown threads."""
    t = _threads.get(thread_id)
    if not t:
        return False
    t["deleted_at"] = _now()
    _save()
    return True


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


# ---------------------------------------------------------------------------
# Skills (agentskills.io) — org/user tier rows + built-in enable overrides.
# Same conventions as threads: False for unknown, deleted_at filtering in the
# seam, user_id/org_id reserved as None until Mandate 2. Built-in skills ship
# on disk (trust = code review); callers pass their records in, mirroring how
# `runs` is passed into the thread functions.
# ---------------------------------------------------------------------------

_TIER_ORDER = {"built-in": 0, "org": 1, "user": 2}


def _load_skills() -> None:
    global _skills_loaded
    if _skills_loaded:
        return
    if os.path.isfile(SKILLS_FILE):
        with contextlib.suppress(Exception):
            with open(SKILLS_FILE, "r", encoding="utf-8") as f:
                _skills.update(json.load(f))
    _skills_loaded = True


def _save_skills() -> None:
    os.makedirs(ARTIFACT_BASE, exist_ok=True)
    tmp = SKILLS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_skills, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SKILLS_FILE)


def _skill_summary(skill_id: str, row: dict) -> dict:
    """Light row for listings — no body/files (those are per-skill detail)."""
    return {
        "skill_id": skill_id,
        "name": row["name"],
        "tier": row["tier"],
        "description": row.get("description", ""),
        "source": row.get("source", ""),
        "trust_state": row.get("trust_state", "untrusted"),
        "enabled": bool(row.get("enabled")),
        "file_names": sorted((row.get("files") or {}).keys()),
    }


def list_skills(builtins: list[dict]) -> list[dict]:
    """All tiers merged: disk built-ins (with any enable override applied)
    plus non-deleted org/user registry rows. Grouped by tier, then name."""
    _load_skills()
    out = []
    for b in builtins:
        override = _skills.get(b["skill_id"])
        enabled = b.get("enabled", True)
        if override and not override.get("deleted_at"):
            enabled = bool(override.get("enabled", True))
        out.append(_skill_summary(b["skill_id"], {**b, "enabled": enabled}))
    for sid, row in _skills.items():
        if row.get("tier") == "built-in" or row.get("deleted_at"):
            continue
        out.append(_skill_summary(sid, row))
    out.sort(key=lambda s: (_TIER_ORDER.get(s["tier"], 9), s["name"]))
    return out


def get_skill(skill_id: str, builtins: list[dict]) -> dict | None:
    """Full record (body + files) for the expandable card. None if unknown."""
    _load_skills()
    for b in builtins:
        if b["skill_id"] == skill_id:
            override = _skills.get(skill_id)
            enabled = b.get("enabled", True)
            if override and not override.get("deleted_at"):
                enabled = bool(override.get("enabled", True))
            return {**_skill_summary(skill_id, {**b, "enabled": enabled}),
                    "body": b.get("body", ""), "files": b.get("files") or {}}
    row = _skills.get(skill_id)
    if not row or row.get("deleted_at") or row.get("tier") == "built-in":
        return None
    return {**_skill_summary(skill_id, row),
            "body": row.get("body", ""), "files": row.get("files") or {}}


def install_skill(name: str, tier: str, description: str, source: str,
                  body: str, files: dict) -> dict | None:
    """Insert an org/user skill: untrusted + disabled until reviewed (Phase S
    gate ships with install). Returns the summary, or None on a duplicate
    (tier, name) — the UNIQUE constraint of the B1 schema."""
    _load_skills()
    for row in _skills.values():
        if (row.get("tier") == tier and row.get("name") == name
                and not row.get("deleted_at")):
            return None
    now = _now()
    skill_id = uuid.uuid4().hex  # server-generated, opaque (C3)
    _skills[skill_id] = {
        "name": name,
        "tier": tier,
        "description": description,
        "source": source,
        "trust_state": "untrusted",
        "enabled": False,
        "body": body,
        "files": files,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "user_id": None,
        "org_id": None,
    }
    _save_skills()
    return _skill_summary(skill_id, _skills[skill_id])


def set_skill_enabled(skill_id: str, enabled: bool, builtins: list[dict]) -> bool:
    """Toggle a skill. For built-ins this upserts an override row keyed by the
    deterministic builtin id. Returns False for unknown/deleted skills.
    Trust gating (no enabling untrusted rows) is enforced in the route."""
    _load_skills()
    row = _skills.get(skill_id)
    if row and not row.get("deleted_at"):
        row["enabled"] = enabled
        row["updated_at"] = _now()
        _save_skills()
        return True
    for b in builtins:
        if b["skill_id"] == skill_id:
            now = _now()
            _skills[skill_id] = {
                "name": b["name"], "tier": "built-in", "enabled": enabled,
                "trust_state": "trusted", "source": "repo",
                "description": b.get("description", ""),
                "created_at": now, "updated_at": now, "deleted_at": None,
                "user_id": None, "org_id": None,
            }
            _save_skills()
            return True
    return False


def set_skill_trust(skill_id: str, trust_state: str) -> bool:
    """Review action: flip an org/user row's trust_state. Built-ins are
    repo-managed and never pass through here (route returns 409)."""
    _load_skills()
    row = _skills.get(skill_id)
    if not row or row.get("deleted_at") or row.get("tier") == "built-in":
        return False
    row["trust_state"] = trust_state
    row["updated_at"] = _now()
    _save_skills()
    return True


def soft_delete_skill(skill_id: str) -> bool:
    """Soft-delete an org/user row. Returns False for unknown/built-in."""
    _load_skills()
    row = _skills.get(skill_id)
    if not row or row.get("tier") == "built-in":
        return False
    row["deleted_at"] = _now()
    _save_skills()
    return True

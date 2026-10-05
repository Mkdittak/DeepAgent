# Plan: PostgreSQL storage behind the store seam (Platform 3, slice 1)

## Context

Every durable record except Temporal history and the generated files lives in
JSON under `artifacts/`: the run registry (a dict in `backend/main.py`), the
thread and skill registries (`backend/store.py`), and per-run event logs
(`.events/<run>.jsonl`). Each is a Python dict flushed atomically to a file.
That is correct for exactly one backend process. A second process, or a
backend restart while `claim_legacy.py` runs, silently loses writes (audit:
P1 today, P0 at two processes). A deployed demo for the recruiter event will
cross that line, and the worker's skill seeding assumes it shares a disk with
the API.

The seam was built for this move: `backend/store.py`'s docstring already
carries the Postgres schema (`threads`, `runs`, `events`, `skills`) and every
function takes an optional `Identity`. This slice swaps the bodies for SQL,
pulls the run registry in behind the same seam, and moves the event log into
an `events` table. Conversation memory (SQLite checkpointer) and row-level
security are later, independent steps (HISTORY.md §8).

Decisions taken with the user:
- Postgres runs in **Docker Compose** next to the four existing services.
- Scope is **seam + events** (threads, runs, skills, events). Checkpointer and RLS deferred.
- **JSON stays as the fallback**: `DATABASE_URL` unset = today's behaviour, byte for byte. Same pattern as `AUTH_ENABLED`.

## Design

### Selection and layout

```
backend/store_types.py   Identity (moved out of store.py; shared by both backends)
backend/store_json.py    today's store.py, renamed (git mv), + the run registry and
                         event-log functions moved here from main.py, all async
backend/store_pg.py      same function names, SQL bodies, psycopg3 async pool
backend/store.py         ~30-line facade: `if os.environ.get("DATABASE_URL"):
                         from backend.store_pg import *  else: from backend.store_json import *`
backend/schema.sql       CREATE TABLE IF NOT EXISTS for the four tables + indexes
backend/migrate_json_to_pg.py   one-off: JSON files + JSONL → tables
docker-compose.yml       postgres:16, named volume, healthcheck, port 5432
```

Driver: `psycopg[binary,pool]` (psycopg 3). Chosen over asyncpg because the
future checkpointer step (`langgraph-checkpoint-postgres`) is psycopg-based,
so one driver serves both. One `AsyncConnectionPool` per process, opened
lazily; `store_pg` never imports `backend.main`, so the worker gets a pool by
importing `backend.store` alone.

**Windows event loop.** psycopg's async connections use `loop.add_reader`,
which the default `ProactorEventLoop` on Windows does not provide. Step 3
starts by verifying this against the installed psycopg source (repo rule:
verify library from source, record in `docs/STYTCH_NOTES.md`-style notes). If
confirmed, `backend/main.py` and `temporal/worker.py` set
`asyncio.WindowsSelectorEventLoopPolicy()` on `win32` before anything runs,
and a smoke run confirms Temporal's SDK is fine on the selector loop. If it is
not fine, fall back to `asyncpg` for this slice and accept two drivers later.

### The seam becomes async

Routes are already `async def` and call the seam directly. Both backends
expose `async def` functions and call sites gain `await`. File I/O inside the
JSON backend stays synchronous (microseconds). This is required so a hosted
Postgres never blocks the event loop (the same class of bug as the sync Tavily
client, audit P1).

### Seam interface (both backends)

Unchanged signatures, now async: `ensure_thread`, `owns_thread`,
`touch_thread`, `set_title`, `soft_delete`, `list_threads(identity)`,
`get_thread(thread_id, identity)`, `list_skills`, `get_skill`,
`install_skill`, `set_skill_enabled`, `set_skill_trust`,
`soft_delete_skill`, `backfill_identity`, `claim_identity`,
`reassign_threads`. The `runs: dict` parameter the thread functions take today
disappears; each backend reads its own runs.

New, replacing direct `run_registry` access in `backend/main.py`:

| Function | Replaces |
|---|---|
| `create_run(run_id, row) -> bool` | `run_registry[run_id] = {...}; _save_registry()`; False on duplicate (PK) |
| `delete_run(run_id)` | the rollback in `_start_agent_run` |
| `get_run(run_id) -> row \| None` | `run_registry.get` |
| `run_owned(run_id, identity) -> bool` | `_run_owned` |
| `list_runs(identity) -> [row]` | the loop in `GET /runs`; sort moves to `created_at` from the row (mtime assumed a shared disk). Listing files from `ARTIFACT_BASE/<run_id>` stays until object storage |
| `set_run_status(run_id, status)` | three sites in persister / stream / finalize |
| `known_thread_ids() -> set` | the comprehension in `_start_agent_run` |
| `runs_with_status(status) -> [row]` | startup recovery loop |
| `count_runs_for_org(org_id, since, until) -> int` | `_quota_status` |
| `skill_rows_for_seed(user_id, org_id) -> [row]` | `agent/skills.py._registry_rows` reading the JSON file |

Events (replacing `_save_event`, `_load_events`, `_current_max_offset`):
`append_event(run_id, envelope)` (PG: `INSERT … ON CONFLICT (run_id, event_offset) DO NOTHING`),
`load_events(run_id, from_offset) -> [envelope]`, `max_offset(run_id) -> int`.
The `_persisted_max` in-memory cache stays in `main.py` in front of
`append_event` so a reconnect does not re-insert hundreds of rows; in PG mode
it is seeded once per process from `max_offset(run_id)` instead of scanning a
file. Two backend processes may both run startup recovery and both persist
the same run: that is tolerated by the primary key (`ON CONFLICT DO
NOTHING`), not prevented, and the plan says so in ARCHITECTURE §12.

`_make_run_id` stays **synchronous** and loses its registry pre-check. The
primary key is the collision guard: `create_run()` returns False on a
duplicate and `_start_agent_run` re-rolls the suffix once. `tests/test_run_id.py`
calls `_make_run_id` 2000 times; it keeps asserting distinctness and drops the
registry assertions.

`init()` / `close()`: JSON backend keeps today's import-time load (tests rely
on it). PG backend opens its pool **lazily on first call** (`_ensure_pool()`),
applies `schema.sql` once, and the lifespan `init()` is only the eager path
for the real server. Reason: `tests/auth_harness.py` and `test_health.py` use
`TestClient(app)` without `with`, so startup handlers never run there, and the
worker needs the lazy path anyway.

Import-time work in `main.py` that would need the DB (`_load_registry()`,
`store.load()` A3 archive, `_backfill_legacy_identity()`) moves into the PG
backend's first-open path. The JSON backend keeps doing it at import so the
harness is untouched. The PG backend **never runs the A3 "archive everything
on first load"**: the migration carries each thread's existing `deleted_at`,
and on a fresh database there is nothing to archive.

### Hot-path change

`_v1_envelope` currently reads `run_registry.get(run_id)` **per event** for
`user_id`/`org_id`. With a database that is one query per token batch.
Resolve the pair once when a stream or persister opens and pass it in. This
is a strict improvement for the JSON backend too.

### Schema (from the store.py docstring, with two fixes)

- `events(run_id, event_offset, ts, type, payload jsonb, user_id, org_id, PRIMARY KEY (run_id, event_offset))`. Column is `event_offset` because `offset` is reserved; the wire envelope keeps `offset`.
- `skills`: the docstring's `UNIQUE (tier, name, user_id, org_id)` does not match the Python rule (an org row is unique per org, but `_stamp` records the installer's `user_id`, so two members could install the same org skill; soft-deleted rows would also block re-install). Use two **partial unique indexes** instead: `(name, org_id) WHERE tier='org' AND deleted_at IS NULL` and `(name, user_id, org_id) WHERE tier='user' AND deleted_at IS NULL`. For flag-off rows (`org_id IS NULL`) the Python 409 check in `install_skill` remains the guard, as today.
- Indexes: `runs(thread_id)`, `runs(org_id, created_at)` for the quota count, `threads(updated_at)`, `skills(tier, org_id)`.
- Timestamps `timestamptz`; `count_runs_for_org(org_id, since, until)` receives tz-aware bounds for the server's local day. Rows with no `created_at` (pre-August) get it derived from the run-id tail by the migration (`_run_created_at`), NULL only if that fails, and NULL rows do not count toward quota, matching today.

### Worker

`agent/skills.py.seed_files` becomes `async` and calls
`store.skill_rows_for_seed(user_id, org_id)`; the tenancy filter
`_row_in_scope` stays in Python for the JSON backend and becomes a `WHERE`
for PG. `temporal/activities.py` awaits it. The worker already calls
`load_dotenv()`, so it sees `DATABASE_URL`.

### CLIs

- `backend/claim_legacy.py`: use the seam (`claim_identity`, `reassign_threads`) via `asyncio.run` instead of reading the registry file directly; works against either backend. "Stop the backend first" still applies in JSON mode; in PG mode it does not, and the docstring says both.
- `backend/migrate_json_to_pg.py`: reads `.run_registry.json`, `.thread_registry.json`, `.skill_registry.json`, every `.events/*.jsonl`; inserts with `ON CONFLICT DO NOTHING`; prints counts; `--dry-run`. Run once when switching.

### Docker Compose and start.bat

`docker-compose.yml`: `postgres:16`, `POSTGRES_DB/USER/PASSWORD=deepagent`,
volume `pgdata`, `ports: 127.0.0.1:5433:5432` (5433 on the host so a native
Postgres on 5432 never collides), `healthcheck: pg_isready`.
`.env.example` gains a commented
`DATABASE_URL=postgresql://deepagent:deepagent@127.0.0.1:5433/deepagent`
(plain `postgresql://`, no `+asyncpg` dialect suffix).
`start.bat` runs `docker compose up -d` before the four windows, ignoring
failure (no Docker = JSON mode).

## Learning companions (standing rule from the user, applies to all work from now on)

The user wants to understand every piece of code and every design choice as it
is written. So:

- A `learning/` directory at the repo root, listed in `.gitignore` so it stays
  uncommitted. `learning/README.md` is the index.
- **Every new code file gets `learning/learning_<filename>.md`**, written in
  the same step as the code. Substantially refactored files (`store_json.py`,
  `main.py`) get one too.
- Each companion has: (1) the concept in plain terms and where it sits in the
  system; (2) the design choice and the alternatives rejected, with the reason;
  (3) the libraries used, with each function, its arguments and what the
  return value is, verified from the installed source in `.venv` rather than
  memory; (4) a walkthrough of the file's own functions and why each argument
  exists; (5) three to five mastery questions, answers at the bottom under a
  heading so they can be hidden.
- **Research by subagent.** Before writing each file, launch one
  general-purpose agent to gather the facts for the companion: read the
  relevant installed package source (psycopg, psycopg_pool, FastAPI lifespan,
  LangGraph), the official docs, and the existing code the file touches. The
  agent returns a fact sheet; the companion and the code are then written
  together. Agents run in parallel where files are independent.
- Companions to produce in this slice, in order:
  `learning_postgres_migration_overview.md` (primer before any code: the seam
  pattern, why JSON breaks at two processes, connection pools, async drivers
  and the Windows loop, `ON CONFLICT`, partial unique indexes, `jsonb`,
  lifespan vs import time), then one per file: `store_types.py`,
  `store_json.py`, `store.py` (facade), `store_pg.py`, `schema.sql`,
  `migrate_json_to_pg.py`, `docker-compose.yml`, `claim_legacy.py` (changed),
  `skills.py` (changed), `main.py` (changed), `test_store_contract.py`.
- Each commit message says which companions were written for it.

## Files

| File | Change |
|---|---|
| `backend/store.py` → `backend/store_json.py` | git mv; functions `async def`; absorb `run_registry`, `_save_registry`, `_load_registry` (incl. the artifact-dir scan and `.corrupt` handling), `_save_event`, `_load_events`, `_current_max_offset` from main.py; thread functions read the local registry instead of a `runs` param |
| `backend/store_types.py` | new: `Identity` |
| `backend/store.py` | new facade |
| `backend/store_pg.py` | new: pool, `init()` applying `schema.sql`, every seam function in SQL |
| `backend/schema.sql` | new |
| `backend/main.py` | remove registry globals and event-file helpers; `await store.*` everywhere; lifespan calls `store.init()`; identity resolved once per stream/persister; `_quota_status` → `count_runs_for_org`; `_make_run_id` → `run_exists`; recovery → `runs_with_status` |
| `agent/skills.py` | `seed_files` async via `store.skill_rows_for_seed`; drop the file read |
| `temporal/activities.py` | `await seed_files(...)` |
| `backend/claim_legacy.py` | seam-based, async |
| `backend/migrate_json_to_pg.py` | new |
| `docker-compose.yml`, `start.bat`, `.env.example` | as above |
| `pyproject.toml` | add `psycopg[binary,pool]>=3.2`; pytest marker `postgres` |
| `tests/auth_harness.py` | `reset_state` pokes `store_json._threads`, `_skills`, `_loaded`, `_skills_loaded`, `THREADS_FILE`, `SKILLS_FILE` and the moved `run_registry` (these are the user's uncommitted pytest-conversion edits; commit those first) |
| `tests/test_registry.py` | import `_save_registry` / `_load_registry` / `REGISTRY_FILE` from `store_json` |
| `tests/test_flag_off.py` | `m.run_registry`, `h.store._threads`, `h.store._skills` → `store_json.*`; `m._v1_envelope` gains the pre-resolved identity argument |
| `tests/test_quota.py` | iterates `m.run_registry` and calls sync `_quota_status` → `await store.count_runs_for_org` |
| `tests/test_run_id.py` | reads `h.m.run_registry` / `h.m.REGISTRY_FILE` → `store_json`; distinctness-only for the 2000-id loop |
| `tests/test_skills.py` | monkeypatches `store.SKILLS_FILE`, `store._skills`, `store._skills_loaded` and `skills_mod.SKILL_REGISTRY_FILE` (deleted) → `store_json.*`; await `seed_files` |
| `tests/test_org_scope.py` | await `seed_files` |
| `tests/test_store_contract.py` | new: one checklist of seam behaviours (ownership → 404 semantics, soft delete, skill trust gating, duplicate install incl. org-tier by two members, event append/dedup/replay, quota count, backfill + claim). Imports `store_json` and `store_pg` **directly** (the facade picks at import time and reads `ARTIFACT_BASE` at import, so it cannot be parametrized). JSON case points at a tmp dir; PG case skips unless `DATABASE_URL_TEST` is set and `TRUNCATE … CASCADE`s the four tables in a fixture between cases |
| `docs/ARCHITECTURE.md` §10, `docs/REFERENCE.md` §2 + §6, `docs/RUNNING.md` (new "Optional: PostgreSQL" section), `docs/HISTORY.md` (F16, Platform 3 → 🟡 slice 1 done) | documentation |

## Order of work (each a commit, pushed)

0. Save the learning-companion rule to memory; add `learning/` to `.gitignore`; write `learning/README.md` and the overview primer (subagent research first).
1. `test:` commit the user's pending pytest conversion + `test_health.py` (pre-existing work; must land first so the harness edits below are a diff on top of it).
2. `refactor(store):` rename to `store_json.py`, add `store_types.py` + facade, make the seam async, absorb the run registry and event helpers; update main.py call sites; identity-once in envelopes. **Behaviour identical; all existing tests green.**
3. `feat(store):` verify psycopg's Windows loop requirement from source and pick the loop policy; then `store_pg.py` (lazy pool) + `schema.sql` + compose + env + dependency + lifespan `init()`.
4. `feat(worker):` async `seed_files` via the seam.
5. `feat(cli):` migrate script; claim tool on the seam.
6. `test:` contract test over both backends; `postgres` marker.
7. `docs:` the four docs.

## Verification

1. **Fallback untouched**: with `DATABASE_URL` unset, `pytest` passes (includes `test_flag_off`, `test_idor`, `test_registry`, `test_run_id`, `test_skills`), and `proof_smoke.py` / `proof_pastruns.py` behave as before.
2. **Postgres path**: `docker compose up -d`; set `DATABASE_URL`; `pytest -m postgres` (contract test) passes; start the stack; run `proof_smoke.py`, `proof_resume.py`, `proof_pastruns.py`, `proof_noviewer.py`, `proof_backend_restart.py` (recovery reads `runs_with_status` from PG and events from the table).
3. **Multi-process proof** (the point of the slice): start two backend processes on :8000 and :8001 against the same DB; create a run on one, list and replay it from the other.
4. **Tenancy with PG**: `AUTH_ENABLED=true` + `DATABASE_URL`; the six auth suites via the harness pointed at PG (`DATABASE_URL_TEST`); `proof_auth_live.py` if Stytch keys are present.
5. **Migration**: run `migrate_json_to_pg.py --dry-run` then for real on the current `artifacts/`; sidebar shows the same threads in PG mode; `psql` row counts match file counts.
6. `ruff check . && ruff format --check .` clean.

## Out of scope (next slices)

Checkpointer → `langgraph-checkpoint-postgres`; row-level security policies
with `SET LOCAL app.user_id/app.org_id` per request; artifacts → object
storage; a migration tool (Alembic) once the schema changes a second time.

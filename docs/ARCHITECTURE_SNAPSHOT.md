# Architecture snapshot (2026-10-13, branch `feat/postgres-store`)

Facts about the code as it is. Every claim cites a file. "NOT FOUND" means the repo was searched and nothing exists.

## 1. Repo layout + how it runs

```
agent/        context.py core.py skills.py tools.py
backend/      auth.py claim_legacy.py main.py store.py
temporal/     activities.py worker.py workflows.py
frontend/     index.html vite.config.ts package.json package-lock.json
  src/        App.tsx main.tsx auth/ components/ components/blocks/ net/ store/ styles/
  tests/      localstorage_degradation.ts
skills/built-in/  slide-deck/SKILL.md  web-research/SKILL.md + references/
tests/        auth_harness.py sse_client.py check_wf.py proof_*.py test_*.py README.md
docs/         ARCHITECTURE.md AUTH.md HISTORY.md REFERENCE.md RUNNING.md STYTCH_NOTES.md plans/postgres-store.md
artifacts/    (gitignored except .gitkeep) .run_registry.json .thread_registry.json .skill_registry.json .events/*.jsonl .checkpoints.sqlite <run_id>/
.temporal.db  start.bat  pyproject.toml  .env  .env.example
```

**Entrypoints / commands** (`start.bat:21-37`, `README.md:34-39`):

```
temporal server start-dev --db-filename .temporal.db --ip 127.0.0.1 --port 7233 --ui-port 8233
python -m temporal.worker
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log   # start.bat
python -m backend.main                                                              # README; reload=True, main.py:1052-1058
cd frontend && npm run dev                                                          # Vite on :3000, vite.config.ts:6-8
```

**Python**: `requires-python = ">=3.11"` (`pyproject.toml:12`); venv is 3.13.5. Deps in `pyproject.toml:18-45` (`deepagents>=0.6.0`, `temporalio>=1.10.0`, `langgraph-checkpoint-sqlite>=2.0.0`, `stytch>=15.3.0`, ...). Installed: deepagents 0.7.8, temporalio 1.32.0, langgraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1. Python lockfile: NOT FOUND. Node lockfile: `frontend/package-lock.json`.

**Env vars** (all read via `os.environ.get` after `load_dotenv()`): `GOOGLE_API_KEY` (consumed by langchain-google-genai), `TAVILY_API_KEY` (`agent/tools.py:56`), `TEMPORAL_ADDRESS` (`backend/main.py:391`, `temporal/worker.py:25`), `ARTIFACT_BASE` (`backend/main.py:65`, `backend/store.py:65`, `agent/skills.py:36-38`, `temporal/activities.py:115,153`), `CORS_ORIGINS` (`main.py:54`), `HOST` (`main.py:1057`), `WORKER_MAX_CONCURRENT_ACTIVITIES` (`worker.py:33`), `AUTH_ENABLED` (`backend/auth.py:58`), `STYTCH_PROJECT_ID/SECRET/ENV` (`auth.py:95-97`), `ARTIFACT_SIGNING_SECRET`, `ARTIFACT_SIGN_TTL_SECS` (`main.py:271-275`), `RUN_QUOTA_PER_ORG_PER_DAY`, `AGENT_RECURSION_LIMIT` (`main.py:316-320`). Frontend: `VITE_API_BASE` (`frontend/src/net/api.ts:8-10`), `VITE_STYTCH_PUBLIC_TOKEN` (`frontend/src/auth/stytch.ts:16`). Templates: `.env.example`, `frontend/.env.example`.

## 2. Persistence

| Store | Path | Owner | Single-process? |
|---|---|---|---|
| Run registry | `$ARTIFACT_BASE/.run_registry.json` | `backend/main.py:66,70,150-213` | Yes: module dict `run_registry`, whole-file rewrite on every save |
| Thread registry | `$ARTIFACT_BASE/.thread_registry.json` | `backend/store.py:66,70,127-134,156-189` | Yes: module dict `_threads`, loaded once (`_loaded`) |
| Skill registry | `$ARTIFACT_BASE/.skill_registry.json` | written by `backend/store.py:67,76,400-418`; read cross-process by worker `agent/skills.py:36-38,228-242` | API side single-writer; worker re-reads file each run |
| Event log | `$ARTIFACT_BASE/.events/<run_id>.jsonl` | `backend/main.py:67,83-147` | Append-only; dedup cache `_persisted_max` is per-process (`main.py:80`) |
| Checkpointer | `$ARTIFACT_BASE/.checkpoints.sqlite` | `temporal/activities.py:152-156` | SQLite file opened per activity |
| Artifacts | `$ARTIFACT_BASE/<run_id>/<file>` | `agent/tools.py:174-178,217-221,259-264`; served `main.py:425-453` | Worker writes, API reads: shared disk assumed |
| Temporal history | `.temporal.db` | Temporal dev server (`start.bat:21`) | n/a |
| Browser | `localStorage["deepagent_session_v1"]` | `frontend/src/store/store.ts:18,43-82` | per browser |

Writes to the three JSON registries go temp-file + `os.fsync` + `os.replace` (`main.py:157-163`, `store.py:127-134,411-418`). `backend/claim_legacy.py:33-44` rewrites the run registry from a separate process and its docstring (`:9-10`) says to stop the backend first.

Run registry record (`artifacts/.run_registry.json`, written at `main.py:771-781`):

```json
"without-using-any-tools-or-searching_2026-09-17_23-09-44": {
  "workflow_id": "agent-without-using-any-tools-or-searching_2026-09-17_23-09-44",
  "user_message": "Without using any tools or searching, ...",
  "status": "done",
  "thread_id": "92a70540552c45e491bc3b3db8edb8fc",
  "created_at": "2026-09-17T23:09:44.780008-05:00",
  "user_id": "member-test-2529a40a-...", "org_id": "organization-test-303bbf9d-..."
}
```

Thread record (`store.py:293-301`): `{"title","created_at","updated_at","deleted_at","user_id","org_id"}` keyed by `uuid4().hex`. Skill record (`store.py:510-525`): `{"name","tier","description","source","trust_state","enabled","body","files","created_at","updated_at","deleted_at","user_id","org_id"}` keyed by `uuid4().hex` or `builtin-<name>` (`store.py:549-561`). Event line: see §4. Current counts: 120 runs, 107 threads, 21 skill rows, 97 event files.

**Checkpointer**: `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver.from_conn_string(path)` opened inside the activity and closed in `finally` (`temporal/activities.py:150-157,440-443`), passed to `create_deep_agent(checkpointer=...)` (`agent/core.py:46-68`). Tables `checkpoints` and `writes` (library-created); 1226 checkpoint rows over 78 thread_ids today. Thread key is `config["configurable"]["thread_id"]` (`activities.py:228-229`).

**Postgres**: code, schema files, migrations, drivers: NOT FOUND (no psycopg/asyncpg/alembic/sqlalchemy in `pyproject.toml` or venv). The target schema exists only as a docstring in `backend/store.py:7-54` and the plan `docs/plans/postgres-store.md`.

## 3. Auth + users

**User store**: NOT FOUND in this repo. Users are Stytch B2B members; the backend never stores them. Only `user_id` (member_id) and `org_id` (organization_id) are stamped on run/thread/skill rows (`store.py:117-120`). Dev helper files `artifacts/.demo_people.json` and `.demo_member_ids.json` exist but no code reads them (grep: NOT FOUND). Redacted example from `.demo_people.json`:

```json
"alice": {"email": "<redacted>", "org": "Acme Corp",
          "org_id": "organization-test-303bbf9d-...", "roles": ["stytch_member","stytch_admin"]}
```

**Token**: Stytch session JWT in `Authorization: Bearer` plus opaque `X-Session-Token` (`backend/auth.py:26-28,128-138`). Issued by Stytch via the prebuilt `<StytchB2B>` Discovery UI, magic link + Google OAuth, 480-minute session (`frontend/src/auth/Login.tsx:23-32`). Validated by the FastAPI dependency `get_principal` (`auth.py:157-182`): `client.sessions.authenticate_jwt_async` local JWKS check, any failure 401. `reverify_network` (`auth.py:185-236`) calls `sessions.authenticate_async` with an `AuthorizationCheck(org_skills/manage)` on org-skill writes only (`main.py:564-581`). `require_role("stytch_admin")` at `auth.py:239-245`.

Flag off (`AUTH_ENABLED` unset): every request is `LEGACY_PRINCIPAL` (`auth.py:78-80,165-166`).

**Routes without `get_principal`**: `GET /health` (`main.py:401-403`) and `GET /artifacts/{run_id}/{filename}` (`main.py:425-453`), which instead requires an HMAC `exp`+`sig` query minted by `GET /artifacts/{run_id}/{filename}/sign` (`main.py:271-295,411-422`). Every other route takes `p: Principal = Depends(get_principal)`.

**Org/tenant**: yes. `Principal(user_id, org_id, roles)` (`auth.py:62-67`); `store.Identity(user_id, org_id)` (`store.py:84-94`). Scoping points: runs `_run_owned` (`main.py:249-256`) used by `/runs`, cancel, stream, sign; threads `_owned` (`store.py:97-101`) in list/get/set_title/soft_delete/owns_thread; skills `_skill_visible` (`store.py:104-114`) and worker-side `_row_in_scope` (`agent/skills.py:213-225`); quota per org (`main.py:323-364`). Events carry `user_id`/`org_id` copied from the run row (`main.py:698-706`). Memory (checkpointer) is keyed by thread_id only; no identity check in `activities.py:228-229`. Identity reaches the worker through `WorkflowInput` (`temporal/workflows.py:20-36`) and is never re-derived (`activities.py:34-37`).

## 4. Event stream / live feed

**Transport**: SSE only. WebSocket: NOT FOUND (only a stale comment, `agent/tools.py:5`). Endpoint `GET /runs/{run_id}/stream` (`main.py:964-1045`); frame is `id: <offset>\ndata: <json>\n\n` (`main.py:987-988`), `: ping` every 15 s when idle (`main.py:961,1017-1020`).

Real event (`artifacts/.events/...jsonl`):

```json
{"v": 1, "run_id": "without-using-any-tools-or-searching_2026-09-17_23-09-44", "offset": 1,
 "ts": "2026-09-18T04:09:45.711072+00:00", "user_id": "member-test-2529a40a-...",
 "org_id": "organization-test-303bbf9d-...", "type": "skill.activated", "name": "web-research",
 "tier": "built-in", "path": "/skills/built-in/web-research/SKILL.md", "description": "Structured web research workflow ..."}
```

**Types** (`main.py:691-747`, mirrored in `frontend/src/store/types.ts:17-41`): `run.started{prompt}`, `text.delta{text}`, `tool.started{step_id,name,args}`, `tool.progress{step_id,tool,message}`, `tool.finished{step_id,name,status,output_preview,duration_ms}`, `plan.snapshot{todos}`, `skill.activated{name,tier,path,description}`, `file.created{filename,url}`, `run.error{message}`, `run.finished{state,summary?,artifacts?,note?}`. Older files under `.events/` still hold the pre-v1 shape `{"type":"progress","event_type":...,"seq":...}` (e.g. `create-alist-of-rent-prices-in_2026-08-18_17-19-00.jsonl`).

**Durable stream**: the activity publishes `AgentProgress` dataclasses to a Temporal `WorkflowStream` topic `"progress"` (`temporal/workflows.py:45-46`, `activities.py:130-132`); Temporal assigns `offset`. The backend's `_persist_run` background task subscribes from offset 0 and appends every envelope to JSONL (`main.py:812-833`, started at `main.py:944`). **Replay**: if `describe().status != RUNNING` the route streams `_load_events(run_id, from_offset)` from JSONL (`main.py:981-993,114-132`); otherwise it subscribes live with `from_offset` (`main.py:995-1035`). **Last-Event-ID**: header parsed to `from_offset = last_id + 1` (`main.py:978-979`).

**Frontend**: fetch-based reader (not EventSource) so it can send auth headers and `Last-Event-ID` (`frontend/src/net/sse.ts:13-85`). `controller.ts` opens one stream per run, replays each run of a thread in order and attaches live to a last run with `status === "running"` (`controller.ts:58-74`), and resumes streaming runs from `lastOffset` on page load (`controller.ts:85-94`). Reducer `store.ts:163-287` handles all ten types; dedup by offset `store.ts:299`. Rendering: `components/BlockView.tsx` to `blocks/{Text,Tool,Plan,Skill,Artifact,Error}Block.tsx`.

## 5. Temporal

**Workflow** `AgentWorkflow.run` (`temporal/workflows.py:39-84`): executes one activity and returns its string result; queries `is_done`, `get_result`. **Activity** `run_deep_agent` (`temporal/activities.py:106-475`): creates artifact dir, opens checkpointer, builds agent, seeds skills, iterates `agent.astream_events(version="v2")`, publishes progress, lists produced files, returns final text.

Task queue `"deep-agent-queue"` (`workflows` caller `main.py:64`, `worker.py:21`). Worker: `Worker(client, task_queue, workflows=[AgentWorkflow], activities=[run_deep_agent], max_concurrent_activities=$WORKER_MAX_CONCURRENT_ACTIVITIES or 10)` (`worker.py:35-41`). Activity options (`workflows.py:63-70`): `start_to_close_timeout=15 min`, `heartbeat_timeout=5 min`, `RetryPolicy(initial_interval=2s, maximum_interval=30s, maximum_attempts=3)`, `cancellation_type=WAIT_CANCELLATION_COMPLETED`. Heartbeats: `activity.heartbeat("invoking agent")` once, then `"processing"` on every stream event (`activities.py:159,284`).

**Payloads**: `WorkflowInput{run_id, user_message, thread_id, user_id, org_id, recursion_limit}` (`workflows.py:20-36`) and `AgentInput` with the same fields (`activities.py:30-38`); size is the prompt plus ids. Output: `str` final response (`activities.py:475`). Stream payloads `AgentProgress` (`activities.py:42-55`): `llm_token` batches flushed every 50 ms (`:168,298-301`), `output_preview` capped at 500 chars (`:370`), args values capped at 500 chars (`:65-77`). Skill files and messages are not in Temporal payloads; they live in the LangGraph state/checkpointer.

**Local run**: Temporal CLI dev server with SQLite file `.temporal.db` (`start.bat:21`). Docker / compose files: NOT FOUND.

## 6. Agent core

**Framework**: `deepagents.create_deep_agent` on LangGraph (`agent/core.py:5,59`). **Model**: `"google_genai:gemini-3.6-flash"` only (`core.py:60`). Backend `StateBackend()` virtual filesystem (`core.py:58,69`).

**Tools**: project tools (`core.py:62-67`, `agent/tools.py`): `web_search` Tavily, 5 results, wrapped untrusted (`tools.py:63-93`); `generate_pptx` writes `presentation.pptx` (`:131-179`); `generate_xlsx` writes `results.xlsx` (`:187-222`); `generate_html` writes `index.html` (`:230-265`). deepagents built-ins (`.venv/.../deepagents/graph.py:293-300`, `middleware/filesystem.py`): `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `delete` on the in-state FS; `execute` returns an error on non-sandbox backends (`filesystem.py:1322`); `task` subagent tool. `write_todos` from `TodoListMiddleware` (`core.py:92`).

**Context per step**: system prompt is `SYSTEM_PROMPT` (`core.py:13-43`) plus `SkillsMiddleware` injecting `SKILLS_SYSTEM_PROMPT` with the skill list from `/skills/built-in`, `/skills/org`, `/skills/user` (`core.py:79-87`, `agent/skills.py:291-310`). Skill files are seeded into the `files` state channel per run (`activities.py:238-242,275-283`; `skills.py:245-285`). Memory read/write is the checkpointer: state is loaded by `thread_id` on invoke and written by LangGraph after each step (`activities.py:150-157,227-229`); `aget_state` is read once per continued turn to re-announce skills (`activities.py:252-273`). deepagents `MemoryMiddleware`/`memory=` is not passed (`core.py:59-96`). **Injection boundary**: `web_search` output only; each result becomes `<untrusted_web_content source="...">{json}</untrusted_web_content>` behind `_UNTRUSTED_PREAMBLE` (`tools.py:99-123`). Skill bodies and files are injected unwrapped.

**Cancel**: `POST /runs/{id}/cancel` calls `handle.cancel()` (`main.py:948-958`); the activity catches `CancelledError`, publishes `cancelled`, re-raises (`activities.py:416-427`). **Worker kill**: Temporal retries the activity (3 attempts); `seq` restarts but the stream `offset` keeps increasing, and the UI dedups by offset (`store.ts:299`; `tests/test_retry_offset.py`). **Backend restart**: `_recover_running_runs` on startup re-attaches the persister for still-running workflows and appends a backfilled `text.delta` + `run.finished` for finished/gone ones (`main.py:845-925`).

## 7. Existing file handling

Upload endpoint: NOT FOUND. Only `POST /skills` accepts text content (`body` + `files: dict[str,str]`), with bundle-path checks for empty and `..` segments (`main.py:584-618`); no size limit. Files are written by the three generator tools into `RunContext.artifact_dir` (`tools.py:35-41`, `agent/context.py:31-39`, set at `activities.py:200-210`). deepagents `write_file`/`edit_file` touch only the in-state virtual FS. Serving: `_resolve_artifact` realpath containment (`main.py:298-307`); `.html/.htm` returned inline unless `?download=1` (`main.py:442-453`). The UI renders HTML in `<iframe sandbox="allow-scripts">` (`blocks/ArtifactBlock.tsx:124,160-165`). Size or MIME validation on serve: NOT FOUND.

## 8. Frontend

React 19 + TypeScript 5.7 + Vite 6, `@stytch/react`, `react-markdown` + `remark-gfm` + `rehype-sanitize` (`frontend/package.json`). Build: `tsc && vite build`; dev `vite` on port 3000 (`vite.config.ts`). Layout: `src/net/` (`api.ts` REST, `sse.ts`, `controller.ts` lifecycle), `src/store/` (`store.ts` custom `useSyncExternalStore` store, `types.ts`), `src/auth/` (`stytch.ts`, `Login.tsx`), `src/components/` + `blocks/`. No router; `App.tsx:26` toggles chat/skills view. Base URL: `VITE_API_BASE` else `http://<hostname>:8000` (`api.ts:8-10`). Auth: `authHeaders()` reads `client.session.getTokens()` and sends both headers on every REST and SSE call (`stytch.ts:40-50`, `api.ts:14-19`, `sse.ts:26`); `main.tsx:11-22` mounts `StytchB2BProvider` only when the public token is set; `App.tsx:85-103` gates on `useStytchMemberSession`. Persistence: `localStorage` key `deepagent_session_v1` holds threadId, run order, turns, lastOffset (`store.ts:43-82`); cleared on sign-out (`AccountMenu.tsx:47`).

## 9. Tests + proof scripts

Pytest config `pyproject.toml:95-106` (`testpaths=tests`, `test_*.py`, `asyncio_mode=auto`). Commands from `tests/README.md`; run from repo root unless noted.

| Path | Proves | Command |
|---|---|---|
| `tests/test_health.py` | `/health` returns ok | `.venv\Scripts\python.exe -m pytest tests\test_health.py` |
| `tests/test_run_id.py` | run_id suffix uniqueness, 409 on duplicate | `.venv\Scripts\python.exe -m pytest tests\test_run_id.py` |
| `tests/test_registry.py` | corrupt registry quarantined, atomic save | `.venv\Scripts\python.exe tests\test_registry.py` |
| `tests/test_concurrency.py` | contextvar isolation across runs | `.venv\Scripts\python.exe tests\test_concurrency.py` |
| `tests/test_untrusted.py` | untrusted envelope on search results | `.venv\Scripts\python.exe tests\test_untrusted.py` |
| `tests/test_envelope.py` | AgentProgress to v1 mapping | `.venv\Scripts\python.exe tests\test_envelope.py` |
| `tests/test_traversal.py` | artifact path containment | `.venv\Scripts\python.exe tests\test_traversal.py` |
| `tests/test_offset_dedup.py` | offset vs seq dedup across retry | `.venv\Scripts\python.exe tests\test_offset_dedup.py` |
| `tests/test_skills.py` | built-in SKILL.md spec, seed layout, scripts excluded | `.venv\Scripts\python.exe tests\test_skills.py` |
| `tests/test_idor.py` | cross-tenant reads 404 | `.venv\Scripts\python.exe tests\test_idor.py` |
| `tests/test_forged_jwt.py` | real `get_principal` rejects bad JWTs | `.venv\Scripts\python.exe tests\test_forged_jwt.py` |
| `tests/test_org_scope.py` | org skills invisible to other org, API + worker seed | `.venv\Scripts\python.exe tests\test_org_scope.py` |
| `tests/test_admin_gate.py` | member 403 on org-skill writes; `reverify_network` mapping | `.venv\Scripts\python.exe tests\test_admin_gate.py` |
| `tests/test_quota.py` | N+1 run per org per day is 429 | `.venv\Scripts\python.exe tests\test_quota.py` |
| `tests/test_flag_off.py` | AUTH_ENABLED=false is a no-op | `.venv\Scripts\python.exe tests\test_flag_off.py` |
| `tests/test_retry_offset.py` | offsets unique across activity retry (needs Temporal) | `.venv\Scripts\python.exe tests\test_retry_offset.py` |
| `tests/test_memory.py` | multi-turn recall via SQLite checkpointer (needs Gemini key) | `.venv\Scripts\python.exe tests\test_memory.py` |
| `tests/test_finished_replay.py` | finished run replays from JSONL (needs stack) | `cd tests && ..\.venv\Scripts\python.exe test_finished_replay.py` |
| `tests/proof_smoke.py` | POST /runs to run.finished | `cd tests && ..\.venv\Scripts\python.exe proof_smoke.py` |
| `tests/proof_resume.py` | Last-Event-ID resume, no dup | same pattern |
| `tests/proof_two_tabs.py` | two readers, identical offsets | same pattern |
| `tests/proof_pastruns.py` | watched run replays after completion | same pattern |
| `tests/proof_noviewer.py` | unwatched run replays (background persister) | same pattern |
| `tests/proof_keepalive.py` | `: ping` on idle stream | same pattern |
| `tests/proof_kill_worker.py` | worker kill mid-run, retry streams cleanly | same pattern |
| `tests/proof_backend_restart.py` | backend restart mid-run, persister re-attached | same pattern |
| `tests/proof_auth_live.py` | end-to-end tenancy against real Stytch | `.venv\Scripts\python.exe tests\proof_auth_live.py` |
| `frontend/tests/localstorage_degradation.ts` | store survives hostile localStorage | `cd frontend && node_modules/.bin/esbuild tests/localstorage_degradation.ts --bundle --platform=node --format=esm --outfile=../artifacts/_degrade.mjs && node ../artifacts/_degrade.mjs` |

Helpers, not tests: `tests/auth_harness.py`, `tests/sse_client.py`, `tests/check_wf.py`. CI config: NOT FOUND.

## 10. Single-process assumptions and rough edges

- `backend/main.py:70` `run_registry` module dict; every route reads it and `_save_registry` (`:150-163`) rewrites the whole file. Two API replicas overwrite each other's rows.
- `backend/main.py:80` `_persisted_max` per-process offset cache; a second replica's persister would append duplicate offsets (dedup on read at `:114-132` masks it).
- `backend/main.py:812-833,944` `_persist_run` runs as an `asyncio.create_task` in whichever replica took `POST /runs`; `_recover_running_runs` (`:891-920`) runs in every replica on startup.
- `backend/store.py:70-77` `_threads`, `_skills`, `_loaded`, `_skills_loaded` module globals loaded once; cross-replica writes are invisible until restart.
- `backend/main.py:275` `_ARTIFACT_SECRET` random per process when `ARTIFACT_SIGNING_SECRET` unset; signed links fail on another replica.
- `backend/main.py:72,388-393` `_temporal_client` module singleton. `backend/auth.py:89,109-115` `_client` Stytch singleton. `agent/tools.py:50-60` `_tavily_client` singleton.
- `backend/main.py:323-343` quota counts from in-memory `run_registry` using server-local calendar day.
- `agent/skills.py:36-38,231-233` worker reads `.skill_registry.json` from the same disk as the API; `temporal/activities.py:114-118` and `backend/main.py:468-475,298-307` assume API and worker share `$ARTIFACT_BASE`.
- `temporal/activities.py:152-156` each concurrent activity opens the same SQLite file; two workers on different hosts would not share conversation memory.
- Hardcoded paths: `tests/proof_kill_worker.py:6`, `tests/proof_backend_restart.py:7` (`C:\Mukund's Projects\DeepAgent`); `tests/sse_client.py:6`, `tests/check_wf.py:4,8`, `tests/proof_noviewer.py:467`, `tests/proof_pastruns.py:493` (`localhost:8000` / `localhost:7233`).
- `backend/main.py:923-925` uses deprecated `@app.on_event("startup")`.
- `backend/claim_legacy.py:9-10,33-44` requires the backend stopped; otherwise the in-memory registry overwrites its edit.
- `frontend/src/store/store.ts:24-25` module-level `state` and listeners; `controller.ts:8-9` module-level `streams` map and `activeRunId`.

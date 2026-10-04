# DeepAgent — Architecture

*How the system works today. For endpoint, event and env-var tables see
[REFERENCE.md](REFERENCE.md); for setup see [RUNNING.md](RUNNING.md); for auth
design see [AUTH.md](AUTH.md); for how it got here see [HISTORY.md](HISTORY.md).*

---

## 1. Layers

```
┌───────────────────────────────────────────────────────────────────┐
│ React UI (frontend/, Vite :3000)                                   │
│  sidebar of conversations · composer · plan/tool/skill/file blocks │
│  skills manager · Stytch login gate (optional)                      │
└───────────────┬───────────────────────────────────────────────────┘
                │ REST (POST /runs, /threads, /skills) + SSE (GET /runs/{id}/stream)
┌───────────────▼───────────────────────────────────────────────────┐
│ FastAPI (backend/, :8000)                                          │
│  main.py  routes, v1 event envelope, JSONL persistence, recovery   │
│  auth.py  Principal resolution (Stytch B2B, behind AUTH_ENABLED)   │
│  store.py threads + skills registry (JSON files, Postgres-shaped)  │
└───────────────┬───────────────────────────────────────────────────┘
                │ Temporal client: start_workflow · WorkflowStream subscribe
┌───────────────▼───────────────────────────────────────────────────┐
│ Temporal (temporal/, server :7233, UI :8233)                       │
│  workflows.py  AgentWorkflow = one activity per run                 │
│  activities.py run_deep_agent: drives the agent, publishes events  │
│  worker.py     process that executes both                          │
└───────────────┬───────────────────────────────────────────────────┘
                │ in-process call
┌───────────────▼───────────────────────────────────────────────────┐
│ Deep Agent (agent/)                                                │
│  core.py    create_deep_agent: Gemini 3.6 Flash, middleware, tools │
│  tools.py   web_search · generate_pptx · generate_xlsx · generate_html │
│  skills.py  Agent Skills seeding + validation                      │
│  context.py per-run ContextVar (artifact dir, callbacks, identity) │
└───────────────────────────────────────────────────────────────────┘
```

The backend contains no AI logic. The worker contains no HTTP. Identity is
resolved exactly once, in the API, and flows down as plain data.

---

## 2. Life of a request

1. **Browser → `POST /runs`** with `{message, thread_id?}` plus the two auth
   headers when auth is on. The route resolves the caller to a `Principal`,
   checks the per-org daily quota, mints a run id of the form
   `<slug>_<YYYY-MM-DD_HH-MM-SS>_<6 hex>`, and a workflow id `agent-<run_id>`.
2. **Thread resolution.** A client may *echo* a thread id it already owns to
   continue a conversation. An unknown or unowned id silently starts a fresh
   thread with a server-minted `uuid4().hex`, so nothing is confirmed about
   other tenants' ids. The thread record is created on this first message
   (title = first 80 chars of the prompt).
3. **Registry row** `{workflow_id, user_message, status: running, thread_id,
   created_at, user_id, org_id}` is written atomically to
   `.run_registry.json`. Then `start_workflow(AgentWorkflow, WorkflowInput)`.
   A `WorkflowAlreadyStartedError` rolls the row back and returns 409.
4. **Background persister.** The API spawns `_persist_run`, which subscribes
   to the run's durable stream from offset 0 and appends every event to
   `.events/<run_id>.jsonl` until a terminal event. This runs whether or not a
   browser is watching, so every finished run is replayable.
5. **Browser opens the SSE stream** `GET /runs/{id}/stream`. While the
   workflow is RUNNING the route subscribes live; once it has finished the
   route replays the JSONL instead (a completed Temporal workflow no longer
   answers poll updates).
6. **Worker executes `run_deep_agent`** (details in §4) and publishes
   `AgentProgress` records to the workflow's `progress` topic.
7. **Backend maps each record to a v1 envelope**, stamps it with the stream
   offset, persists it, and writes it as an SSE record with `id: <offset>`.
8. **Frontend reduces each event** into blocks on the current assistant turn,
   deduplicating by offset. A refresh resumes with `Last-Event-ID`, so nothing
   is replayed twice.

### Durability guarantees

| Failure | What happens |
|---|---|
| Browser closes | Workflow keeps running. On reload the store finds the streaming run in localStorage and reopens the stream from its last offset. |
| Backend restarts | On startup every run still marked `running` is checked against Temporal. Still RUNNING → the persister is re-attached from offset 0 (dedup fills the gap). Finished or gone → a visible "stream interrupted" notice and a terminal `run.finished` are appended so Past Runs never shows a silent truncation. |
| Worker dies mid-run | Temporal retries the activity (3 attempts, 2 s → 30 s backoff). Offsets keep increasing across attempts, so the UI never splices or drops text. A second `run.started` renders as a fresh turn. |
| Two runs on one worker | Each activity has its own `RunContext` ContextVar; artifact directory and callbacks never cross. The worker caps concurrent activities (default 10). |

---

## 3. The event stream

### Offsets, not sequence numbers

The worker stamps each `AgentProgress` with a per-attempt `seq`. That number
restarts at 0 when an activity retries, which caused dropped and spliced text
in the original UI. The canonical identity of an event is therefore the
**offset assigned by Temporal's durable workflow stream**, which is monotonic
for the life of the workflow. The backend is the first place the offset is
visible, so persistence and the SSE `id:` both live there.

### The v1 envelope

Every event on the wire has this base:

```json
{ "v": 1, "run_id": "...", "offset": 42, "ts": "2026-09-28T10:00:00+00:00",
  "user_id": null, "org_id": null, "type": "text.delta", "...": "payload" }
```

`user_id` and `org_id` are filled from the run's registry row and are null for
runs created with auth off. The ten `type` values and their payloads are
listed in [REFERENCE.md §3](REFERENCE.md#3-event-types). Internally the
worker uses older names (`llm_token`, `tool_start`, …); the single mapping
function `_v1_envelope` in `backend/main.py` is the only place that knows
both vocabularies.

### Transport details

- SSE records are `id: <offset>\ndata: <json>\n\n`.
- Live streams send `: ping` every 15 s when idle. The keepalive timer sits
  on an internal queue, never on the Temporal subscription iterator, because
  cancelling that iterator reads as end-of-stream.
- The frontend reads SSE with `fetch` rather than `EventSource` because it
  must send `Authorization`, `X-Session-Token` and `Last-Event-ID` headers.
- Cancel is `POST /runs/{id}/cancel`, which cancels the workflow; the activity
  catches the cancellation and publishes a `cancelled` terminal.

---

## 4. Inside the worker

`run_deep_agent` (temporal/activities.py) does the following per run:

1. Creates `ARTIFACT_BASE/<run_id>/` and publishes `run_start`.
2. Opens the **conversation checkpointer**, an `AsyncSqliteSaver` on
   `ARTIFACT_BASE/.checkpoints.sqlite`, and builds the agent with it. Runs
   that share a `thread_id` share LangGraph state, which is what gives
   multi-turn memory.
3. Binds a **`RunContext`** (run id, artifact dir, progress callback, file
   callback, thread id, user id, org id) to the activity's asyncio task via a
   `contextvars.ContextVar`. Tools read it instead of any process global.
4. **Seeds skills** (§6) into the agent's virtual filesystem for this tenant.
   On a continuing thread it also scans the checkpoint for `SKILL.md` reads
   from earlier turns and announces them as *Skill in context*.
5. Streams the agent with `astream_events(version="v2")` and translates:
   - `on_chat_model_stream` → `llm_token`, coalesced every 50 ms.
   - `on_tool_start` for `write_todos` → `plan` with the structured todo
     list; for `read_file` on a seeded `SKILL.md` → `skill` then
     `tool_start`; otherwise `tool_start` with key-redacted args.
   - `on_tool_end` → `tool_end` with a 500-char output preview and duration.
   - `on_custom_event` `tool_progress` and the RunContext callback → live
     `tool_progress` lines (search queries, URLs read).
   - Tool file writes call the file callback → `file` at write time.
6. On `CancelledError` publishes `cancelled`; on any other exception publishes
   `error` and re-raises so Temporal can retry. Always closes the
   checkpointer.
7. Scans the artifact directory, publishes one `artifact` per file, then
   `done` with the final text (first 500 chars) and the file list.

Workflow settings: 15 min start-to-close, 5 min heartbeat, 3 attempts,
`WAIT_CANCELLATION_COMPLETED`. The workflow itself publishes nothing; the
activity owns the whole stream.

---

## 5. The agent

`agent/core.py` calls `create_deep_agent` with:

- **Model** `google_genai:gemini-3.6-flash`.
- **System prompt** that makes `write_todos` the mandatory first tool call,
  requires reading a matching skill's `SKILL.md` next, caps web searches
  (1–2 per task, hard limit 3), forbids repeated identical calls, and routes
  HTML to `generate_html` rather than `write_file`.
- **Custom tools** in `agent/tools.py`: `web_search` (async Tavily, 5 results,
  output wrapped in `<untrusted_web_content>` with a "data not instructions"
  preamble), `generate_pptx`, `generate_xlsx`, `generate_html`. Each file tool
  writes into the run's artifact dir and emits a `file` event immediately.
- **Backend** `StateBackend`, so deepagents' filesystem tools operate on a
  virtual filesystem in LangGraph state, not on disk, and `execute` hard-errors.
- **Middleware** `SkillsMiddleware` (three sources: built-in, org, user, in
  that priority order) with an instruction-only prompt, and
  `TodoListMiddleware` wired explicitly because deepagents 0.7.8 stopped
  adding it automatically.
- **Recursion limit** per run from `WorkflowInput` (default 30; 15 was tried
  and hit `GraphRecursionError` on ordinary tasks).

---

## 6. Skills

DeepAgent implements the open **Agent Skills** standard (agentskills.io): a
skill is a folder with a `SKILL.md` whose YAML frontmatter has `name` and
`description`, followed by instructions, optionally with `references/` and
`assets/` files.

**Progressive disclosure.** Every model call sees only each skill's name and
description. When the task matches, the model reads the full `SKILL.md` with
one `read_file`; the worker turns that read into a `skill.activated` event.
References are read only when the skill tells the model to.

**Three tiers**, mirroring the planned memory tiers:

| Tier | Where it lives | Trust | Who manages |
|---|---|---|---|
| built-in | `skills/built-in/<name>/` in the repo | code review | repo; admins may toggle project-wide |
| org | `.skill_registry.json` rows with `org_id` | review in the Skills manager | org admins (network-verified RBAC) |
| user | `.skill_registry.json` rows with `(user_id, org_id)` | review in the Skills manager | the owning member |

**Seeding.** Before each run `seed_files(user_id, org_id)` builds a
`{virtual_path: content}` map at `/skills/<tier>/<name>/...` from built-ins
(minus any disable override) plus org/user rows that are **both enabled and
trusted** and visible to this tenant. It is passed as the `files` state
channel. `scripts/` directories and path-traversing keys are never seeded:
v1 is instruction-only and "exec off" holds at the data layer and the tool
layer.

**Install gate.** `POST /skills` validates the spec strictly (name regex,
description length, bundle paths) and returns 422 on violation, 409 on a
duplicate `(tier, name)`. New rows land **untrusted and disabled**. Enabling
requires `trusted`; revoking trust also disables. An untrusted skill is never
injected, not even its description, which is stricter than the framing used
for search results because a skill is written to be obeyed.

Two built-ins ship today: `slide-deck` and `web-research`.

---

## 7. Threads and memory

A **thread** is a conversation: a server-minted id, a title, timestamps, a
soft-delete flag and an owner. Runs point at threads via the registry row.
`GET /threads` powers the sidebar; `GET /threads/{id}` returns the runs in
order, which the frontend replays one by one (attaching live to the last one
if it is still running).

**Memory M0** is the LangGraph checkpointer keyed by `thread_id`. Later turns
see earlier messages, including skill files already read. The checkpoint file
survives restarts. User-tier and org-tier memory are designed but not built;
see [HISTORY.md](HISTORY.md#open-items-and-roadmap).

---

## 8. Auth and tenancy in one paragraph

Behind `AUTH_ENABLED` (default off). On, every request carries a Stytch
session JWT (verified locally against cached JWKS) and an opaque session token
(sent to Stytch only for org-skill writes, with an RBAC check). The result is
an immutable `Principal(user_id, org_id, roles)`; every store call is scoped
on it; unknown and unowned both answer 404; artifacts are fetched via 60-second
HMAC-signed URLs because iframes cannot send headers; each org has a daily run
quota. Off, every request is a fixed legacy principal and the code paths
collapse to the pre-auth behaviour. Full design, rationale and demo script in
[AUTH.md](AUTH.md).

---

## 9. Frontend

```
App                      session gate: /authenticate → Login → Shell
└─ Shell
   ├─ Sidebar            threads (grouped by recency), New chat, Skills view
   ├─ Header             connection dot, sidebar toggle, AccountMenu (auth)
   ├─ Conversation       turns for every run in the current thread
   │  └─ TurnView → BlockView → TextBlock | ToolBlock | PlanBlock |
   │                             SkillBlock | ArtifactBlock | ErrorBlock
   ├─ Composer           Send / Stop, consistent with connection state
   ├─ JumpPill           "jump to latest"
   └─ SkillsManager      tier groups, trust chips, review-gated toggles, install
ErrorBoundary wraps the tree.
```

- **`store/store.ts`** holds normalized state `{threadId, order, runs}` where
  each run has `turns`, `state`, `lastOffset`, `seenOffsets`. One reducer
  applies a v1 event with granular immutable updates, so only the active text
  block re-renders while streaming. React binds via `useSyncExternalStore`.
- **`net/api.ts`** wraps `fetch` with `API_BASE` (from `VITE_API_BASE`,
  default `http://<host>:8000`) and the Stytch headers.
- **`net/sse.ts`** is a hand-rolled fetch-based SSE parser that sets
  `Last-Event-ID`.
- **`net/controller.ts`** owns the lifecycle: `submit`, `cancel`, `newChat`,
  `loadThread` (replay finished runs, attach live to a running one),
  `resumeOnLoad`.
- **Persistence** is `localStorage` under `deepagent_session_v1`, treated as a
  progressive enhancement: corrupt, disabled, full or absent storage all
  degrade to in-memory.
- **Markdown** renders through `react-markdown` + `remark-gfm` with
  `rehype-sanitize` mandatory.
- **Artifacts** preview in a sandboxed `<iframe>` (scripts allowed, no
  same-origin), expand to a full-viewport overlay in the same sandbox, and
  download with `?download=1` so model HTML is never rendered top-level at the
  API origin. With auth on, every preview and click first mints a signed URL.
- No router: the sidebar switches the main pane between chat and skills.
- Design tokens for light and dark themes; no web font dependency.

---

## 10. Storage on disk

Everything lives under `ARTIFACT_BASE` (default `./artifacts`), all gitignored:

| Path | Contents | Written by |
|---|---|---|
| `<run_id>/` | generated files (`.pptx`, `.xlsx`, `.html`) | worker tools |
| `.run_registry.json` | run_id → workflow id, prompt, status, thread, owner, created_at | API, atomic tmp+rename; corrupt files are moved to `.corrupt` and logged |
| `.events/<run_id>.jsonl` | one v1 envelope per line, offset-deduped | API persister and live stream |
| `.thread_registry.json` | thread_id → title, timestamps, deleted_at, owner | API via `store.py` |
| `.skill_registry.json` | org/user skill rows + built-in enable overrides | API via `store.py`; read by the worker when seeding |
| `.checkpoints.sqlite` | LangGraph conversation checkpoints | worker |

`start.bat` also passes `--db-filename .temporal.db` so the Temporal dev
server persists workflow history at the repo root. Without that flag the dev
server is in-memory and loses every workflow on restart.

`store.py`'s docstring carries the Postgres schema these files map onto one to
one. Swapping the function bodies for SQL is the planned path; the API and
frontend do not change.

---

## 11. Security properties

- Artifact paths are resolved with `realpath` and must stay inside
  `ARTIFACT_BASE`; traversal and missing files are both 404.
- Backend binds `127.0.0.1` and allows CORS only from the dev frontend
  origins unless overridden.
- HTML artifacts are served inline only for the sandboxed iframe; the
  Download button forces `Content-Disposition: attachment`.
- Web search results are framed as untrusted data per source.
- Tool arguments are redacted by key pattern (`key|token|secret|password|
  auth|credential`) and truncated before they reach the stream.
- With auth on: 401 bodies are generic (the reason is logged server-side),
  visibility is checked before authorization, bearer and session token must
  belong to the same session.

---

## 12. Known limits

- The JSON stores are correct for one backend process. A second process is
  the trigger for the Postgres move.
- Row scoping relies on every query passing the identity; database row-level
  security is the production step.
- A completed workflow's events come from JSONL only. Temporal dev-server
  retention is 24 h.
- The event persister treats the first `error` as terminal, so a retried
  attempt after an agent exception is not visible in the stream.
- JWT revocation lags up to 5 min on hot paths by design.
- There is no evaluation harness for agent output quality.

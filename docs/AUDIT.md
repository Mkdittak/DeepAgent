# DeepAgent Audit — Running Log

> Durable copy of the audit record. Originally kept in the session plan file
> (`~/.claude/plans/`, session scratch); copied here so it survives. Covers the
> seven-phase audit (Phases 0–7) plus the execution sprint and the frontend
> rewrite. Line/file references reflect the state at the time each note was
> written and may have shifted after later edits.

## Context
Owner requested a phased read-only audit of the DeepAgent codebase (Phases 0–7 with stop-gates). Read-only until owner approves fixes. This file is the auditor's running record so later phases don't lose earlier findings.

## Phase 0 — completed
Full codebase read (~2,150 LOC app code). Key facts:
- Stack: FastAPI + Temporal (workflow_streams contrib) + deepagents/Gemini 3.5 Flash + Tavily; React 19/Vite/TS, single 1,295-line App.tsx, no state lib.
- Files: backend/main.py (321), temporal/activities.py (257), agent/tools.py (154), temporal/workflows.py (53), agent/core.py (38), temporal/worker.py (28), frontend/src/App.tsx (1295), main.tsx (8).
- No git repo, git not installed. No tests, CI, lint, error tracking.
- Real API keys in .env (Google, Tavily).
- `DeepAgent/` nested dir = stale full duplicate of older version (own node_modules) — DELETE candidate.
- frontend/dist = stale build. Storage: filesystem only — artifacts/, .run_registry.json, .events/*.jsonl. No DB, no auth, no tenancy.

## Seeded findings (verified in later phases)
- Path traversal in GET /artifacts/{run_id}/{filename} — os.path.join with unsanitized segments; run_id=".." + filename=".env" may serve secrets. HTMLResponse serving of artifacts = stored XSS surface.
- Per-run `os.environ["ARTIFACT_DIR"]` mutation + module-global `_progress_cb` → cross-run corruption under concurrent activities on one worker.
- sync TavilyClient.search called in async tool blocks worker event loop; new client per call.
- deepagents built-in tools (write_todos, filesystem, execute, task); injection surface for Phase 5.
- CORS allow_origins=["*"] + bind 0.0.0.0 + zero auth.
- Frontend: setTurns full deep-clone per event (O(n) per token); stale-closure connect; reconnect loop risk; one-conversation-only UI; index-as-key; tool_progress step attribution heuristic wrong when tools overlap.
- generate_html interpolates LLM HTML unescaped; iframe sandbox="allow-scripts" partial mitigation.
- Backend synthesises "done" if stream ends without terminal — may mislabel failed runs.
- Registry status only updated while a WS client is attached — status drift when no viewer.

## Owner directives (2026-08-24, after Phase 0)
- Python env: project `.venv` (Anaconda base Python 3.13.5); requirements installed & imports verified. temporalio 1.32.0, deepagents 0.7.8, langchain-core 1.6.0, langchain-google-genai 4.3.5, fastapi 0.141.1, tavily-python 0.8.0. Code written against deepagents 0.6.x — watch for API drift.
- `DeepAgent/DeepAgent` stale dup: treat as DELETE.
- Mandate 0.5: frontend must be competitive with Claude/Gemini chat UIs. Mandate 0.5 + Mandate 1 = ONE project: a frontend REWRITE.
- Phase 2 top priority — streamed text corruption: assistant text drops chunks / splices fragments. Test 3 hypotheses; verify any fix is structural not timing-dependent.
- Phase 1 must-answer: does process restart lose the in-memory run registry? Does .run_registry.json have write locking? If concurrent runs can corrupt it → P0.
- Phase 4 = frontend rewrite w/ no-regression rule: produce PARITY SPEC first; keep App.legacy.tsx until sign-off; extract components over from-scratch.
- Mandate 2 needs auth+tenancy (don't exist); mandate 3 needs a real datastore (JSON file today).

## Phase 1 — completed
Library semantics verified from installed source (.venv):
- workflow_streams (temporalio 1.32.0 contrib, EXPERIMENTAL): publishes = Signals batched by publisher (default batch_interval=2s → ~2s event bursts); subscribe = long-poll Updates, poll_cooldown 100ms, offset-addressed durable log in workflow state, exactly-once via publisher_id+sequence, ordered. Every poll grows workflow history. Backend batch_interval=50ms is publish-side config on a subscriber → dead config.
- TopicHandle.subscribe default from_offset=0 → EVERY backend reconnect replays full history → _save_event re-appends entire history to JSONL each reconnect (duplicate lines; UI survives via seq dedup).
- deepagents 0.7.8: default backend = StateBackend → built-in fs tools write to LangGraph state (virtual FS), NOT disk; `execute` errors without a sandbox backend; `task` + general-purpose subagent auto-added; write_todos via langchain TodoListMiddleware. Security surface smaller than Phase-0 inference.
- Registry answer: restart does NOT lose registry (persisted each mutation, reloaded + dir-scan backfill). NO locking, NO atomic write. Single asyncio process → concurrent runs cannot interleave (write is sync between awaits) → not corruptible by concurrency TODAY; crash mid-write → truncated JSON → silently swallowed → silent registry reset. P1 now; P0 the moment >1 backend process exists.
- Break-first: (1) activity retry restarts seq at 0 → frontend seenSeqs dedup swallows retried attempt → UI freezes; (2) ARTIFACT_DIR env + _progress_cb global under default worker concurrency; (3) registry status drift + JSONL dup on reconnect.
- README manual instructions omit --db-filename → in-memory Temporal → durability lost on restart; start.bat has it. (Fixed later.)

## Phase 2 — completed
Corruption verdict: (a) ABSENT — setTurns uses functional update. (b) PRESENT variant — duplicate live socket per run: `connect` useCallback deps [runId] + mount effect [connect] → second WS opens with saved localStorage run_id; both feed reduceEvent, masked by seq dedup but doubles subscriptions + JSONL appends; socket 1 leaked. (c) PRESENT = ROOT CAUSE — AgentProgress.seq restarts at 0 on each activity retry; durable log holds attempt1 seqs 0..N then attempt2 seqs 0..M; frontend seenSeqs dedup drops attempt2 seqs ≤N (chunks dropped) and applies seqs >N onto attempt1's partial text (splice). Structural; NOT fixed at audit time.
Other: plan rows = backend emits unstructured str(output)[:500] on "todo" chain-end, no snapshot; frontend merges only adjacent plan blocks. Raw markdown = no renderer. Tool UI = args captured never rendered; duration+output only on tool_end step_id match. Files = artifact events only at end-of-run scan, no live file-created. Reconnect-to-running replays JSONL, marks done, never attaches live. WS drop leaves turn streaming forever. "Open full page" serves agent HTML unsandboxed at API origin. Deep-clone-all-turns per event O(n²). Hardcoded ws://host:8000; vite proxy dead config; no error boundary. KEEP: hasUser replay dedup. DELETE: frontend/dist, vite proxy block, data.step fallback.

## Phase 3 — completed
Backend 10 (ranked): P0 path traversal; P0 zero auth + CORS * + bind 0.0.0.0; P1 agent HTML served unsandboxed same-origin; P1 concurrency corruption (ARTIFACT_DIR env + _progress_cb global, no max_concurrent_activities); P1 seq restart 0 per retry (frontend corruption root); P1 sync TavilyClient.search blocks event loop + new client per call; P1 registry non-atomic write + silent JSONDecodeError swallow (P0 once multi-process); P2 status/JSONL only updated while WS attached; P2 business logic in route handler, provider not swappable cleanly; P2 no retry idempotency.
Also: recursion_limit=30 hardcoded; _redact only by key-name regex; run_id slug collision; no rate limiting; synthetic "done" may mislabel a killed run; artifacts served with no CSP.

## Owner decisions on parity items (2026-08-24)
- Persistent scrollback (append, no wipe on send). Store models multiple runs/turns.
- React 19 + Vite kept; split into components + typed event store + CSS files (no inline CSS string). No heavy UI/state toolkit unless justified.
- UX changes folded in as intentional: typing during runs, Reconnect attaches to LIVE runs, examples fill-not-send.

## Phase 4 — PARITY SPEC + REWRITE ARCHITECTURE (design)
Keystone fix: canonical event id = the durable stream's global offset, not activity seq. `WorkflowStreamItem.offset` is monotonic and never resets across retries → seq-collision corruption structurally impossible.
Transport: SSE for the stream + REST for control. `POST /runs`, `POST /runs/{id}/cancel`, `GET /runs/{id}/stream` (SSE, id:=offset, Last-Event-ID→from_offset). SSE's native Last-Event-ID reconnect maps 1:1 onto offset addressing.
Event schema v1: `{ v:1, run_id, offset, ts, type, user_id, org_id }` + discriminated payloads (run.started/status/finished, text.delta, plan.snapshot{todos}, tool.started/progress/finished, file.created, run.error). user_id/org_id nullable from the start.
Component tree: ErrorBoundary > App(store) > Header, RunsPanel, Conversation, Composer, JumpPill; blocks Text/Tool/Plan/Artifact/Error. Per-component CSS.
Store: normalized by run_id, events ordered by offset, granular immutable updates (only active text block re-renders; no deep-clone). Markdown via react-markdown + rehype-sanitize (sanitize mandatory).
Slices S0 (scaffold) → S1 (SSE+offset+REST) → S2 (markdown+tools) → S3 (plan+files) → S4 (scrollback+polish).

## Phase 5 — memory + injection defense (design)
- BIG FINDING: DeepAgent has NO conversational memory even within a session. Each browser send → new workflow with only that message. No memory/store/checkpointer/thread_id anywhere.
- Reuse installed primitives (no new datastore): StoreBackend (namespace-scoped, wildcard-injection-rejecting validator + semantic search); MemoryMiddleware (wraps memory in <agent_memory> with "data not instructions" guidance); checkpointer= param (langgraph-checkpoint installed).
- 3 tiers: Context = checkpointer keyed thread_id (no auth needed); User = StoreBackend ns(user_id) (needs mandate-2 auth); Org = StoreBackend ns(org_id) = cross-tenant surface. Storage = LangGraph BaseStore: InMemory dev, Postgres prod = the same datastore mandate 3 needs.
- Injection surfaces: web_search output returned raw (live exploit); tool outputs; org memory as persistence vector. Defenses: untrusted-content framing (copy MemoryMiddleware pattern), provenance tags, arg validation, HITL for irreversible/org-writes.
- Cross-tenant leak test: A poisons org memory → B obeys. Vulnerable today? No, vacuously (no memory/users). Safe-once-built requires gated writes + untrusted-framing + provenance + structural separation.

### Phase 5 corrections (owner)
- C1: M1 (injection framing) MUST precede M0 (memory) or ship together — memory makes injection persistent.
- C2: user-tier writes need gating too — no auto-promote from a turn that included untrusted tool output.
- C3: thread_id server-generated, opaque, unguessable; never trust client-supplied ids for read.

## Phase 6 — scale to 1000 (design)
Assumptions: 1000 users, ~50 concurrent peak (~17 avg by Little's Law), 300k runs/mo, ~6 LLM calls/run, 0 browser/subprocess.
- Token carry: memory + SummarizationMiddleware ~11k input/call steady-state vs ~3.2k amnesiac → ~3.5×; memory ≈ triples LLM spend.
- Bottlenecks by failure point: ~2 concurrent runs/worker (globals) — app not correct at 2 today; ~2 backend procs (registry JSON); local-disk artifacts/events unshared; Temporal dev SQLite + history growth; poll RPS from SSE; LLM RPM + Tavily free tier.
- Statefulness fixes: registry→Postgres; ARTIFACT_DIR env→per-run context; _progress_cb→per-run; local disk→object storage. Strength: Temporal offset-addressed stream = any node resumes any run → SSE needs no sticky sessions, no added Redis/Kafka.
- Cost (price flagged): ~$4,500/mo LLM + ~$2,700/mo Tavily + ~$1–1.5k infra ≈ $8–9k/mo; amnesiac baseline ~$1,300/mo LLM.
- Headline: app breaks at 2 concurrent today — "scale to 1000" = "make correct at 2, then scale".

### Phase 6 corrections (owner) / C4–C6
- C4 (resolved against source): poll = Temporal Update, publish = Signal; both grow history. AgentWorkflow = 1 activity then completes → ~250–300 events/run, never near 50k under normal use. SSE design survives with: M0 threads persist in Postgres (workflows stay per-run), continue_as_new/truncate safety valve, backend fan-out for poll RPS. No move off Temporal.
- C5: non-idempotent retries add ~12% cost (normal) to ~35% (rate-limit storm), self-amplifying.
- C6: per-user/org quotas enforced at POST /runs; recursion_limit=30 too generous → lower ~15, per-tier.

## Phase 7 — verdict + roadmap
- Scorecard /5: correctness 2, error-handling 2, security 1, tenancy 1, observability 1, testing 1, scalability 2, maintainability 2, deployability 2.
- Verdict: strong POC, not-yet-viable product; durability foundation good, app code defeats its guarantees; gap = weeks foundational not polish.
- Roadmap: (A) stop-the-bleeding — git; P0 sec fixes; async-Tavily; atomic-registry. (B) correctness foundation — remove globals → registry→PG + artifacts→object storage → S0 → S1 (SSE+offset, keystone) → observability. (C) mandates in forced order — M1 framing BEFORE M0; M0 context; Mandate 2 auth/tenancy + quotas; M2 user memory (gated writes); M3 org memory (defenses from commit 1); S4. (D) deferred + tripwires — prod Temporal cluster, continue_as_new/truncate, idempotent retries, real execute/sandbox, per-tier recursion_limit.
- Biggest un-asked risk: NO eval harness + NO tests for agent OUTPUT QUALITY — plumbing can be perfect while the product (the answers) is unmeasured.

---

# Execution record

## Sprint (2026-08-25) — Bucket A + concurrency + M0
Env additions: git 2.55.0.3, Temporal CLI 1.8.2, langgraph-checkpoint-sqlite.
- `6b33c53` baseline (28 files; .env/.venv/DeepAgent/ excluded, proven via git check-ignore before commit).
- `6ae5d18` P0 path traversal: reachability confirmed (%2e%2e/.env escapes to root .env); fix = realpath + containment. Proof: legit served, both attacks BLOCKED.
- `a6c7aec` P0 bind 127.0.0.1 (HOST override) + CORS to localhost:3000 (CORS_ORIGINS override).
- `e219eea` P1 removed unsandboxed "Open full page" link.
- `a1009ec` P1 async Tavily (AsyncTavilyClient) + reused client.
- `e4260be` P1 atomic registry write (tmp+os.replace+fsync) + corrupt JSON preserved as .corrupt & logged.
- `5440546` P1 per-run RunContext (contextvars) replaces process globals; worker max_concurrent_activities. Proof: 2 interleaved runs, 0 cross-contamination.
- `caa99a9` P1 offset dedup: backend stamps item.offset; frontend dedups by offset. Proof (real WorkflowStream forced retry): offsets [0..5] unique, seq restarts; seq-dedup drops 3, offset-dedup drops 0.
- `c518e90` M1 web_search wrapped `<untrusted_web_content>` + "data not instructions" preamble.
- `d00448f` M0 conversational memory: AsyncSqliteSaver checkpointer; thread_id server-generated uuid4, unguessable. Proof (real Gemini): recall across turns, persists across restart, isolated across thread.

## Frontend rewrite (2026-08-25)
- `22b4487` backend transport: POST /runs, POST /runs/{id}/cancel, GET /runs/{id}/stream (SSE); v1 envelope; structured plan.snapshot from write_todos; file.created at write time.
- `7ba60cc` frontend rewrite: normalized store (offset-ordered, granular immutable, localStorage persist), fetch-SSE with Last-Event-ID, component tree, markdown via react-markdown + rehype-sanitize, per-component CSS. tsc+vite build pass.
- Proofs: refresh-resume no-dup (reconnect at last+1, contiguous), two tabs (identical offsets), kill-worker retry clean (offsets unique across retry, 2 run.started = fresh turn).
- Intentional changes: typing during runs; reconnect attaches live; examples fill-not-send; Past Runs artifacts download-only (no unsandboxed HTML "Open").
- Unasked additions (untested surface): dark mode (prefers-color-scheme); localStorage session persistence; hand-rolled fetch-SSE parser; cosmetic (plan done/total counter, tool status pill, artifact emoji); ErrorBoundary (improvement).

## Deletions (2026-08-25)
- `1c220b6` delete legacy: App.legacy.tsx (+ data.step alias), vite proxy block, backend dead endpoints /ws/chat + /runs/{id}/events + orphaned helpers + unused imports, frontend/dist. Agent run re-verified; build passes.

## Past Runs regression — found and fixed
- Regression: reconnecting to a COMPLETED run delivered 0 events (EMPTY) because a completed Temporal workflow stops accepting poll Updates and the SSE-only rewrite persisted nothing. Applied to ALL finished runs. Retention on dev server = 24h.
- `480c77b` fix: background `_persist_run` task per run subscribes the durable stream and writes each v1 event to per-run JSONL (offset is only known consumer-side, so persistence lives in the backend); `GET /runs/{id}/stream` replays from JSONL when the workflow is finished; SSE keepalive `: ping` every 15s via a pump-task+queue (timing out on the queue, never the subscribe iterator). Proven: finished-run replay (watched + never-watched), keepalive pings, localStorage degradation (corrupt/disabled/quota/absent all degrade in-memory).
- localStorage is a progressive enhancement, not a dependency — app fully demo-able on any machine.

## Startup recovery
- `c720c0a` reconcile 'running' runs on startup: still RUNNING → re-attach persister (subscribe from 0, dedup backfills the gap, continue to real terminal = full recovery); finished/gone → append a visible incompleteness notice + terminal so Past Runs never shows a silent truncation. Proven on disk (re-attach backfilled real terminal, no notice; finalize appended notice + terminal for stale runs).
- Note: during this session Gemini gemini-3.5-flash returned 503 UNAVAILABLE ("high demand") for all runs (external, transient), so a clean COMPLETED end-to-end couldn't be shown; recovery logic is terminal-type-agnostic and fully validated regardless.

## Known limits / Bucket B
- JSONL event store → Postgres event table.
- Runs in flight during a backend restart are re-persisted only once RUNNING is detected on startup (durable log still has them).
- Mandate 2 (auth/tenancy) and Mandate 3 (Postgres datastore, object storage) not started.
- No agent-output-quality eval harness yet.

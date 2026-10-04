# DeepAgent — History

*The record of how the codebase got here: the mandate tracker, a dated
timeline, every security and correctness fix, every feature, the audit that
started it, and what is still open. This file is a log. It is appended to,
not rewritten. Commit hashes are the authoritative detail.*

*Merged on 2026-10-03 from the former `AUDIT.md` (audit record and sprint
log) and `SYSTEM_CHANGES.md` (change catalog), with the mandate tracker
corrected and September's work added.*

---

## 1. Mandates — where we are

Two interlocking tracks of owner mandates: a **platform track** (what the
product must become) and a **memory track** (how the agent remembers, and
how that is kept safe). Legend: ✅ done · 🟡 designed, held · ⬜ not started.

| Mandate | What it is | Status | Delivered by |
|---|---|---|---|
| Platform 0.5 | A frontend competitive with the best chat UIs | ✅ Done 2026-08-26 | F3, F6, F7, F8, F9, F10 |
| Platform 1 | Plan, tools and files visible as first-class UI | ✅ Done 2026-08-27 | F2, F3, C7, planning mandate |
| Platform 2 | Authentication and tenancy | ✅ Done 2026-09-14 → 17 | F12, F13, F14 |
| Platform 3 | Real datastore and object storage | 🟡 Designed, frozen | store seam (F6) carries the schema |
| Memory M1 | Injection framing before any memory | ✅ Done 2026-08-25 | S4 |
| Memory M0 | Context memory within a conversation | ✅ Done 2026-08-25 | F1 |
| Memory M2 | User-tier memory with gated writes | ⬜ Unblocked by Platform 2, not started | — |
| Memory M3 | Org-tier memory, cross-tenant safe | ⬜ Blocked on Platform 3 | — |

Net: a transparent, remembering, multi-tenant agent exists on JSON files and
local disk. What is open is the production storage layer and the two memory
tiers that need it.

---

## 2. Timeline

| Date | What |
|---|---|
| Jul 2026 | Original POC: WebSocket transport, single `App.tsx`, in-memory registry, no tests, no git |
| 2026-08-24 | Seven-phase read-only audit (§6). Verdict: strong POC, app code defeats Temporal's guarantees, breaks at 2 concurrent runs |
| 2026-08-25 | Git initialised. Sprint: P0/P1 security and concurrency fixes, M1 framing, M0 memory. Frontend rewrite with REST + SSE and offset dedup. Legacy code deleted. Past Runs regression found and fixed with JSONL persistence. Startup recovery. First tests |
| 2026-08-26 | Threads + sidebar, artifact overlay, full-bleed layout, palette pass, GFM tables, download hardening, model switched to Gemini 3.6 Flash after two days of 503s |
| 2026-08-27 | Planning made mandatory in the system prompt; plan panel now appears on every run |
| 2026-08-31 | Agent Skills: built-in tier, `skill.activated` event, skill store and REST, Skills manager, two live-run fixes. Thread rename and delete |
| 2026-09-14 | Auth Phases 0–6 in one day: Stytch SDK notes, Principal, scoping, worker identity, login UI, signed URLs + quota, six standalone security tests |
| 2026-09-15 → 16 | Live end-to-end auth proof (77/77). Recursion default back to 30, carried-over skill events, legacy claim tool. AUTH.md |
| 2026-09-17 | `reassign_threads` store function |
| 2026-09-28 | `pyproject.toml` replaces `requirements.txt`; ruff + pytest config; pre-public hardening scan; run-id collision fix (#1); ruff baseline then ruff format across the codebase |
| 2026-10-03 | Documentation consolidated: 12 files → 7 |

---

## 3. Security fixes

### S1 — Path traversal in artifact downloads *(6ae5d18, 2026-08-25)*
`os.path.join` with unsanitised `run_id` and `filename`; `%2e%2e/.env`
escaped to the repo root and served secrets. Fixed with `realpath`
containment inside `ARTIFACT_BASE`. Re-applied on every serve even after the
signed-URL route was added.

### S2 — Open bind and wildcard CORS *(a6c7aec)*
Bound `0.0.0.0` with `allow_origins=["*"]` and no auth. Now `127.0.0.1` and
the dev origins by default, both overridable.

### S3 — Unsandboxed "Open full page" link *(e219eea)*
Model-authored HTML opened top-level at the API origin: stored XSS with the
origin's privileges. Removed; full-page viewing returned in F8 inside the
sandboxed frame.

### S4 — Search results treated as trusted input *(c518e90)*
Tavily output went to the model raw. Now wrapped per source in
`<untrusted_web_content>` with a "data, not instructions" preamble. Shipped
before M0 deliberately: memory would make an injection persistent.

### S5 — Inline download of model HTML *(e1119be, 2026-08-26)*
The Download button fetched HTML inline, reopening S3. Download now uses
`?download=1`, which forces `Content-Disposition: attachment`; the preview
keeps the inline path inside the sandbox.

### S6 — Pre-public hardening scan *(26aadfc, 2026-09-28)*
No secrets in any tracked file or any of 55 commits. `npm audit fix` to zero
vulnerabilities, `pip-audit` clean. README now states that auth-off is
local-only.

Auth-era security *features* (signed URLs, 404-not-403, generic 401 bodies,
mixed-token guard, untrusted-skill exclusion) are under F12 and F13 and
documented in AUTH.md.

---

## 4. Correctness and reliability fixes

### C1 — Process globals shared across runs *(5440546)*
`os.environ["ARTIFACT_DIR"]` and a module-level progress callback meant two
concurrent runs on one worker wrote into each other. Replaced with a per-run
`RunContext` ContextVar; worker concurrency capped. Proven with two
interleaved runs and zero cross-contamination.

### C2 — Non-atomic registry write, swallowed corruption *(e4260be)*
Crash mid-write truncated the JSON, which was then silently reset. Now
tmp + fsync + `os.replace`; corrupt files are moved aside and logged.

### C3 — Events deduplicated by per-attempt sequence *(caa99a9)*
The root cause of streamed text dropping chunks and splicing fragments:
`seq` restarted at 0 on each activity retry, so the UI dropped attempt 2's
low seqs and appended its high ones onto attempt 1's text. Dedup now keys on
the durable stream offset. Proven with a forced retry: offsets unique, seq
dedup dropped 3 events, offset dedup dropped 0.

### C4 — Synchronous Tavily client per call *(a1009ec)*
Blocked the worker event loop and rebuilt the HTTP client every search. Now
one `AsyncTavilyClient`, reused.

### C5 — Finished runs replayed as empty *(480c77b)*
The SSE rewrite persisted nothing, and a completed Temporal workflow stops
answering poll updates, so every finished run showed zero events. Fixed with
a background persister per run writing JSONL, replay from JSONL for finished
runs, and the `: ping` keepalive.

### C6 — Interrupted runs stuck "running" forever *(c720c0a)*
On startup, runs still RUNNING get the persister re-attached; finished or
gone runs get a visible incompleteness notice plus a terminal event.

### C7 — Plan panel silently stopped *(c503b75)*
deepagents 0.7.8 stopped wiring `TodoListMiddleware` automatically, so
`write_todos` vanished without error. Wired explicitly.

### C8 — Markdown tables rendered as pipes *(0446944)*
`remark-gfm` added, a deliberate one-package break of the dependency freeze.

### C9 — Overlong search titles broke layout *(0c05cf1)*
Clamped at 100 chars in the tool and in CSS.

### C10 — Stop/Send lied about connection state *(16fb0e8)*
The control now reflects `connected && streaming`.

### C11 — Model returned 503 for two days *(6b9db28)*
Switched `gemini-3.5-flash` → `gemini-3.6-flash`, as an isolated commit,
against the standing "no swap without an eval harness" rule. A working demo
beat a pristine but broken configuration.

### C12 — Recursion limit 15 too low *(53366ae, 2026-09-16)*
Auth Phase 5 lowered it to 15 per the plan; live runs hit
`GraphRecursionError` after three or four tool calls because planning and
middleware steps count. Restored to 30 and made configurable per run via
`WorkflowInput`.

### C13 — Run-id collision (#1) *(7610d67, 2026-09-28)*
`<slug>_<timestamp to the second>` collided on a double-click or scripted
resubmit: the second run either 500'd on `WorkflowAlreadyStartedError` or
appended into the first run's JSONL where offset dedup dropped every event.
A 6-hex random suffix was added, the duplicate error now rolls back the
registry row and returns 409, and legacy ids without the suffix still parse.
`tests/test_run_id.py` covers it.

---

## 5. Features

### F1 — Conversational memory *(d00448f)*
`AsyncSqliteSaver` checkpointer keyed by a server-minted, unguessable
`thread_id`. Proven: recall across turns, persistence across restart,
isolation across threads.

### F2 — Versioned event contract + REST/SSE transport *(22b4487)*
`POST /runs`, `POST /runs/{id}/cancel`, `GET /runs/{id}/stream`. The v1
envelope reserved `user_id`/`org_id` as null from day one so auth needed no
data migration. Structured `plan.snapshot` from `write_todos`; `file.created`
at write time.

### F3 — Frontend rewrite *(7ba60cc, cleanup 1c220b6)*
One 1,295-line file became a component tree over a normalized store with
granular immutable updates, fetch-based SSE with `Last-Event-ID`,
`react-markdown` + `rehype-sanitize`, per-component CSS, an ErrorBoundary,
dark mode, and localStorage persistence that degrades gracefully. Proven:
refresh-resume with no duplicates, two tabs with identical offsets, kill the
worker mid-run and the retry streams cleanly.

### F4 — Past Runs history *(480c77b, c8d25b5)*
Replayed from JSONL with readable dates and labels.

### F5 — Configurable API origin *(6a2ae3b)*
`VITE_API_BASE`.

### F6 — Thread store seam + endpoints *(4223f84)*
`backend/store.py`: JSON-backed today, with the Postgres schema in its
docstring and signatures designed to be swapped without touching routes.

### F7 — Sidebar + two-column shell *(0144142)*

### F8 — Artifact full-viewport overlay *(44d94a2)*
Same sandboxed frame as the inline preview. Closes by control, backdrop or
keyboard; locks scroll; manages focus.

### F9 — Full-bleed layout with breakout blocks *(fb2f559)*

### F10 — Palette and typography pass *(0846554)*
Slate neutrals, accent discipline, a type scale, design tokens for both
themes, no web font.

### F11 — Agent Skills *(2a55d31, 459cf79, d63a917, 39f8c38, 604dce1, 56ab58b; 2026-08-31)*
Conforms to agentskills.io with deepagents' native `SkillsMiddleware`.
Built-in, org and user tiers; a skill registry behind the store seam;
installs land untrusted and disabled; untrusted skills are never injected at
all; `scripts/` never seeded and `execute` stays stubbed. `skill.activated`
on the stream, a SkillBlock, and a Skills manager view. Two live-run fixes:
seeded files must be `FileData` dicts, and skill-directed `references/`
reads had to be made imperative and exempt from the prompt's speed budget.

### F12 — Authentication and tenancy *(898fa80 → 11a96a8, 2026-09-14)*
Stytch B2B behind `AUTH_ENABLED`. Identity resolved once into a `Principal`;
hybrid verification (local JWT on hot paths, network re-verification with an
RBAC check on org-skill writes); every store call scoped on `(member, org)`;
unknown and unowned both 404; the worker trusts `WorkflowInput` and never
re-derives identity; Discovery login with magic links and Google; legacy
backfill on first start. Six standalone tests (`test_idor`, `test_forged_jwt`,
`test_org_scope`, `test_admin_gate`, `test_quota`, `test_flag_off`) and a
live proof that passed 77 of 77 checks against real Stytch sessions.

### F13 — Signed artifact URLs and per-org quota *(1e6729c)*
60-second HMAC links because iframes cannot send headers; a daily run cap
per org returning 429 with `reset_at` and `Retry-After`.

### F14 — Legacy claim and reassignment *(53366ae, 440b327)*
`backend/claim_legacy.py` moves the `legacy`/`legacy` bucket to a real member
and org, optionally un-archiving; `store.reassign_threads` hands specific
threads to a member. Carried-over skills are announced on later turns of a
thread.

### F15 — Build and tooling *(ddcd759, 5f51ea8, efc4c80, 2026-09-28)*
`pyproject.toml` with a `[dev]` extra, ruff and pytest configuration, ruff
format applied across `agent/ backend/ temporal/ tests/`. The auth and skills
suites and `test_registry` are collected by pytest.

---

## 6. The audit (2026-08-24)

A phased read-only audit of the original POC (~2,150 lines of app code, no
git, no tests). Kept here because the fixes above are its direct output.

**Phase 0, inventory.** FastAPI + Temporal `workflow_streams` contrib +
deepagents 0.7.8 on Gemini + Tavily; React 19 in one 1,295-line file. Real
keys in `.env`. A stale nested duplicate of the repo. Filesystem-only storage.

**Phase 1, library semantics from installed source.** `workflow_streams` is
experimental: publishes are batched Signals, subscribes are long-poll
Updates, both grow workflow history; offsets are durable and exactly-once.
Backend's `batch_interval` on a subscriber was dead config. deepagents'
default `StateBackend` writes to LangGraph state, not disk, and `execute`
errors without a sandbox. The registry survived restart but had no locking
and no atomic write.

**Phase 2, streamed-text corruption.** Three hypotheses tested. Root cause:
per-attempt `seq` restarting on retry (C3). Secondary: a duplicate live
socket per run from a stale-closure effect.

**Phase 3, backend ranking.** P0 traversal; P0 no auth + CORS + bind; P1
unsandboxed HTML; P1 process globals; P1 seq restart; P1 sync Tavily; P1
non-atomic registry; P2 status drift, logic in route handlers, no retry
idempotency.

**Phase 4, rewrite design.** Keystone: canonical event id = durable stream
offset. SSE + REST, with `Last-Event-ID` mapping one to one onto offsets.
Event schema v1 with nullable identity fields. Normalized store, component
tree, sanitised markdown.

**Phase 5, memory and injection.** The agent had no memory at all. Three
tiers designed on installed primitives (checkpointer, `StoreBackend`,
`MemoryMiddleware`). Owner corrections: framing must precede memory;
user-tier writes need gating too; thread ids must be server-minted.

**Phase 6, scale to 1000.** At 1000 users, ~50 concurrent peak, 300k
runs/month: memory roughly triples LLM spend (~$4.5k/month LLM, ~$2.7k
Tavily, ~$1–1.5k infra). Bottlenecks in failure order: the app itself at 2
concurrent runs, the JSON registry at 2 backend processes, local disk,
dev-server SQLite, poll RPS, provider rate limits. Temporal's offset-addressed
stream means any node can resume any run, so no Redis or sticky sessions.
`AgentWorkflow` is one activity then completes, so history growth stays far
from the 50k-event limit under normal use.

**Phase 7, verdict.** Scorecard out of 5: correctness 2, error handling 2,
security 1, tenancy 1, observability 1, testing 1, scalability 2,
maintainability 2, deployability 2. Strong POC, not yet a product. Biggest
unasked risk: no evaluation harness for agent output quality.

---

## 7. Decisions worth remembering

- **Offset over seq.** The one structural fix that made everything else
  possible.
- **Persistence lives in the backend, not the worker,** because the offset is
  only known on the consumer side.
- **Identity resolved once, flows down as data.** The worker has no Stytch
  client on purpose.
- **404 for unowned, visibility before authorization.** Existence is never
  confirmed across tenants.
- **Untrusted skills are excluded, not framed.** A skill is written to be
  obeyed; a search result is merely consulted.
- **No database before the presentation.** Designed, then deliberately
  frozen: a new persistence layer is fresh failure surface for no demo
  benefit.
- **No web font.** Venue wifi.
- **Model swapped under protest.** C11, as its own commit, against the
  standing rule.
- **Recursion 30, not 15.** Measured, not guessed.

---

## 8. Open items and roadmap

Consolidated from the audit's Bucket B, the mandate tracker, AUTH.md's limits
and the pre-audit v2 plan. Nothing here is started unless marked.

**Platform 3 (next major build)**
- Swap `store.py` function bodies to Postgres using the schema in its
  docstring; events JSONL → `events` table with `event_offset`.
- Postgres row-level security so tenancy is enforced by the database, not by
  every query remembering to pass the identity.
- Artifacts to S3-compatible object storage.
- Checkpointer to `langgraph-checkpoint-postgres`.

**Memory**
- M2 user-tier memory: `StoreBackend` namespaced per `(member, org)`, no
  auto-promotion from a turn that saw untrusted tool output.
- M3 org-tier memory: gated writes, provenance tags, untrusted framing,
  structural separation; cross-tenant leak test from the first commit.

**Correctness tripwires**
- Retried activities are invisible to the stream: the persister stops at the
  first `error`. Surface the retry.
- Idempotent retries (non-idempotent retries cost ~12 % normally, ~35 % in a
  rate-limit storm).
- `continue_as_new` or truncation safety valve if any workflow ever
  approaches history limits.
- Per-tier recursion limits.

**Product**
- UI error toasts for 403, 409 and 429 (today a control snaps back or a send
  does not start).
- Browser notifications when a run finishes (frontend only, Notification API).
- Code execution: a sandboxed `execute` (containers first, microVMs at
  scale) with streamed stdout; today `execute` is stubbed and skills are
  instruction-only.
- In-place organisation switch via session exchange instead of the
  sign-in round trip.
- HttpOnly session cookies would need a same-origin proxy design.

**Quality and operations**
- An evaluation harness for agent output quality. Still the biggest unasked
  risk; also the precondition for any future model swap.
- Convert the remaining module-level proof scripts to pytest; a frontend test
  runner; CI.
- Observability: structured logs, request ids, basic metrics.
- Production Temporal cluster instead of the dev server.

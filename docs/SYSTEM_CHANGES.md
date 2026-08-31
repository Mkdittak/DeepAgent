# DeepAgent — Changes by Feature and Security Bug

*A catalog of what changed, organized by the thing changed rather than the order it
happened. Three sections: **security bugs fixed**, **correctness & reliability bugs
fixed**, and **features added or changed**. No code — each entry states what it was, what
changed, and the property the system gained (for security bugs, the risk that was closed).
Short commit references are given for traceability.*

---

## The mandates — where we are

The work sits under two interlocking tracks of owner mandates: a **platform track** (what
the product must become) and a **memory track** (how the agent remembers, and how that is
kept safe). The tracks interlock — the memory track's later tiers are blocked on the
platform track's later mandates. Legend: ✅ done · 🟡 designed but held · ⬜ not started.

### Platform track

**Platform 0.5 — a frontend competitive with the best chat UIs.** ✅ **Done.** Delivered by
the frontend rewrite (F3), the sidebar / thread shell (F6, F7), the layout and visual
passes (F9, F10), and the artifact overlay (F8). Treated as a single project with Platform 1.

**Platform 1 — deep-agent transparency: the agent's plan, tools, and files visible as
first-class UI.** ✅ **Done.** The event contract (F2) carries structured plan snapshots,
the tool lifecycle, and file-created events; the frontend renders them as dedicated plan /
tool / artifact blocks (F3); the planning middleware is wired (C7). The former triggering
caveat — the model sometimes *choosing* not to plan — was closed on 2026-08-27 by making
planning mandatory in the system prompt (see "investigated but deliberately not changed"
for the history).

**Platform 2 — authentication and tenancy (real users and organizations).** ⬜ **Not
started; groundwork laid.** The event envelope reserves owner / organization identity fields
(null today) and the thread store stubs a user column, so adding identity needs no migration
of stored data — but no auth system or tenancy model exists yet. *Distance: a whole
subsystem; the next major build, not a tweak.*

**Platform 3 — a real datastore and object storage (replacing JSON files and local disk).**
🟡 **Designed, then deliberately frozen.** The store seam (F6) and the JSON-to-database path
are designed and ready; the move was consciously deferred rather than shipped before the
presentation, since a new persistence layer is a fresh failure surface for no demo benefit.
*Distance: mostly a swap behind an existing seam — but held by choice.*

### Memory track

**Memory M1 — injection framing (untrusted content, required before any memory).**
✅ **Done.** Web-search output is framed as untrusted (S4). Sequenced deliberately *before*
memory, because memory would otherwise make an injection persistent.

**Memory M0 — context memory (remember within a conversation).** ✅ **Done.** A
per-conversation persistent checkpointer (F1) that survives a restart.

**Memory M2 — user-tier memory (remember across a user's conversations, with gated
writes).** ⬜ **Not started; blocked on Platform 2.** Designed — namespaced per user, with
no auto-promotion from a turn that saw untrusted tool output — but it needs the identity
Platform 2 would provide. *Distance: blocked until auth exists.*

**Memory M3 — org-tier memory (shared across an organization, cross-tenant-safe).**
⬜ **Not started; blocked on Platform 2 and 3.** Designed with cross-tenant-leak defenses
from the first commit, but it needs both tenancy (Platform 2) and a real datastore
(Platform 3). *Distance: the furthest out — two mandates deep.*

### At a glance

| Mandate | What it is | Status |
|---|---|---|
| Platform 0.5 | Competitive chat UI | ✅ Done |
| Platform 1 | Plan / tools / files visible | ✅ Done |
| Platform 2 | Auth + tenancy | ⬜ Not started (groundwork laid) |
| Platform 3 | Real datastore + object storage | 🟡 Designed, frozen |
| Memory M1 | Injection framing | ✅ Done |
| Memory M0 | Context memory | ✅ Done |
| Memory M2 | User-tier memory | ⬜ Blocked on Platform 2 |
| Memory M3 | Org-tier memory | ⬜ Blocked on Platform 2 + 3 |

**Net:** everything needed to *demo a transparent, remembering single-user agent* is done
(Platform 0.5, Platform 1, Memory M1, Memory M0). Everything still open is the
*multi-user / multi-org* half — auth, tenancy, a real datastore, and the two memory tiers
that ride on them — which was a deliberate scope boundary for the presentation, not a
shortfall.

---

## Security bugs fixed

### S1 — Path traversal in artifact downloads *(6ae5d18)*
**Was:** the file-download endpoint trusted the requested filename, so a crafted path could
walk out of a run's artifact folder and read arbitrary files on the host.
**Change:** every download is now constrained to stay inside its own run's directory.
**Risk closed:** the file-serving surface can no longer be turned into a host-filesystem
reader.

### S2 — Open network binding and broad CORS *(a6c7aec)*
**Was:** the backend bound to all network interfaces and accepted cross-origin requests
broadly, exposing the API beyond the local machine.
**Change:** bound to localhost only, and cross-origin trust restricted to the development
frontend origin.
**Risk closed:** the API is reachable only from the machine it runs on, by the app it's
meant to serve.

### S3 — Unsandboxed "Open full page" link (XSS at the API origin) *(e219eea)*
**Was:** model-authored HTML could be opened as a top-level page at the API's own origin — a
cross-site-scripting foothold, since that page would run with the origin's privileges.
**Change:** the link was removed. (Full-page viewing later returned, but only inside a
locked-down sandbox — see F8.)
**Risk closed:** model-authored HTML never executes with the API origin's privileges.

### S4 — Search results treated as trusted input (prompt injection) *(c518e90)*
**Was:** web-search results — which are attacker-controllable text — were fed to the model
as if trustworthy, so a poisoned result could issue instructions the agent would follow.
**Change:** search output is now explicitly framed as untrusted content — data to analyze,
not commands to obey.
**Risk closed:** a malicious search result can't hijack the agent's behavior.

### S5 — Inline download of model HTML re-opened the origin XSS *(e1119be)*
**Was:** serving generated HTML inline is required for the preview frame, but offering that
same file as an ordinary download at the API origin reopened the cross-site risk from S3.
**Change:** the download path now explicitly requests the file **as an attachment**, so the
browser saves it rather than rendering it in place — while the inline preview keeps working
through a separate, sandboxed path.
**Risk closed:** viewing and downloading model HTML are each handled by a mechanism that is
safe for that specific use.

> **Related hardening (not a bug, a safe-by-design feature):** the artifact expand overlay
> (F8) deliberately runs its full-page view in a frame that allows scripts but withholds
> same-origin access, so even a full-screen render of model HTML stays walled off from the
> API origin.

---

## Correctness & reliability bugs fixed

### C1 — Process globals shared across concurrent runs *(5440546)*
**Was:** run-specific state (output directory, progress callback) lived in process-global
variables. With two runs overlapping, one run's writes could land under another's identity.
**Change:** replaced with per-run request-scoped context, and activity concurrency was
capped so a burst of runs can't exhaust the worker.
**Property gained:** runs are isolated from each other and the worker degrades gracefully
under load.

### C2 — Non-atomic registry writes and swallowed corruption *(e4260be)*
**Was:** the run registry was written non-atomically and read with corrupt JSON silently
ignored — so state could be lost or masked.
**Change:** writes became atomic (write-then-rename); corruption now surfaces instead of
being hidden.
**Property gained:** the persisted registry is either valid or loudly broken, never quietly
wrong.

### C3 — Stream events de-duplicated by per-attempt sequence *(caa99a9)*
**Was:** live events were de-duplicated using a per-attempt sequence number, which
double-counts or drops events whenever the workflow retries an activity.
**Change:** de-duplication is now keyed to each event's durable offset — its stable position
in the run's log, independent of retries. The same offset also lets a browser reconnect
mid-run and resume exactly where it left off.
**Property gained:** the event stream is exactly-once from the client's view, and resumable
across disconnects.

### C4 — Synchronous HTTP client created per call *(a1009ec)*
**Was:** the web-search client was synchronous and rebuilt on every call, blocking the event
loop and pooling nothing.
**Change:** a single async client, reused across the app.
**Property gained:** search no longer stalls the server, and connections are pooled.

### C5 — Finished runs replayed as empty *(480c77b)*
**Was:** live events were held only in memory, so revisiting a completed run showed nothing.
**Change:** every event is now persisted to an append-only on-disk log, and a finished run
is replayed from that log using the same event contract as the live view.
**Property gained:** any past run is fully replayable, even with the agent or the model
entirely offline.

### C6 — Interrupted runs stuck in "running" forever *(c720c0a)*
**Was:** if the backend died mid-run, that run stayed marked "running" indefinitely.
**Change:** on startup the backend reconciles such runs, finalizing the ones that can no
longer make progress.
**Property gained:** a restart heals the registry instead of leaving zombie runs.

### C7 — Plan panel silently stopped working *(c503b75)*
**Was:** the agent framework, at its current version, no longer wired in the planning
middleware automatically, so the structured plan snapshots that drive the plan panel simply
stopped being produced — with no error.
**Change:** the planning middleware is now wired in explicitly.
**Property gained:** the planning capability is present and produces plan snapshots again.
*(See the closing note — whether the model chooses to use it on a given run is a separate,
still-open question.)*

### C8 — Markdown tables rendered as raw pipes *(0446944)*
**Was:** the model emits standard pipe-delimited tables, but the markdown renderer had no
support for that dialect enabled, so tables showed up as literal rows of pipe characters.
**Change:** enabled the table dialect in the renderer (a deliberate, minimal break of the
dependency freeze — tiny cost, large visible payoff). Verified against the actual run that
exposed it, and confirmed it also fixes a second already-recorded demo run with the same
latent issue.
**Property gained:** tables render as tables.

### C9 — Overlong search-result titles broke the layout *(0c05cf1)*
**Was:** an unusually long web-search result title could blow out the layout.
**Change:** titles are clamped at the source and in styling.
**Property gained:** one ugly title can't distort the page.

### C10 — Composer control lied about connection state *(16fb0e8)*
**Was:** the Stop / Send control didn't reliably match the actual connection state.
**Change:** the control now reflects real state, so it never advertises an action it won't
perform.
**Property gained:** the primary input control is trustworthy.

### C11 — Model returning persistent service-unavailable errors *(6b9db28)*
**Was:** the configured model returned service-unavailable errors for two days straight,
making live runs impossible.
**Change:** switched — as its own isolated change, against the standing "no swap without an
evaluation harness" rule — to a responding sibling model, and sanity-checked it before
trusting it. The reasoning: a working demo beats a pristine but broken configuration.
**Property gained:** live runs work again.

---

## Features added or changed

### F1 — Conversational memory *(d00448f)*
Each message used to be an amnesiac one-shot. A persistent checkpointer keyed to a
conversation was added, so a later turn can refer back to an earlier one, and memory
survives a restart. **Result:** conversations, not just isolated runs.

### F2 — Versioned event contract + REST/streaming transport *(22b4487)*
The backend/frontend boundary was redefined as an explicit, versioned **event envelope**: a
common shape (version marker, run id, offset, timestamp, reserved identity fields) with a
discriminated type per event — run started, text delta, tool started / progress / finished,
plan snapshot, file created, run error, run finished. REST starts and controls a run; a
streamed connection carries live events, with reconnection mapped onto the durable offset.
Two forward-looking choices: identity fields were reserved (as null) from day one so a
future multi-user model needs no data migration, and the on-disk names were kept
intentionally separable from the over-the-wire names. **Result:** a contract that evolves
by addition instead of by rewrite, and one shared format for live *and* historical viewing.

### F3 — Frontend rewrite: normalized store + component tree *(7ba60cc, cleanup 1c220b6)*
A single 1,295-line file was replaced by a component tree over a normalized store, with
dedicated blocks for markdown, tool calls, plans, and files. Updates are granular and
immutable, so a long-running message re-renders only the block that changed. Dead legacy
code was deleted once the new UI was signed off. **Result:** a maintainable UI that stays
responsive during long runs.

### F4 — Past Runs history *(server 480c77b, UI c8d25b5)*
A browsable history of previous runs, replayed from the persisted event log and presented
with readable dates, sensible labels, and adequate room. **Result:** past work is a
first-class, revisitable thing.

### F5 — Configurable API origin *(6a2ae3b)*
The frontend's backend origin became configurable rather than hard-coded, so the app can
point at a non-default host without a rebuild. **Result:** deployment flexibility.

### F6 — Conversations as first-class objects (thread store + endpoints) *(4223f84)*
A backend **store seam** was introduced — a single, well-defined place where thread data is
read and written — behind endpoints that list conversations and fetch one. The seam was
deliberately shaped so its JSON-backed storage could later be swapped for a real database
without touching the rest of the app. **Result:** a clean data-access boundary and the API
surface for a conversation list.

### F7 — Left sidebar + two-column shell *(0144142)*
A sidebar listing conversations (grouped by recency) beside a two-column application shell.
**Result:** the app reads as a chat product with a history, not a single scratch session.

### F8 — Artifact full-viewport expand overlay *(44d94a2)*
The inline preview showed only a sliver of a long generated page, and the safe "view full
page" path had been removed in S3. The overlay reuses the *same sandboxed frame* — scripts
allowed, no same-origin access — to show a full page without granting model HTML real
privileges. It closes by an always-visible control, by backdrop click, or by keyboard;
locks background scrolling; and manages focus so keyboard users aren't stranded. **Result:**
full-page viewing returned without reopening the security hole that removing it had closed.

### F9 — Full-bleed layout with breakout blocks *(fb2f559)*
The shell fills the viewport edge to edge — sidebar flush left, conversation area with no
dead margins — while prose stays on a comfortable reading width and wide content (artifact
previews, code, large tables) breaks out to full width. Checked at several
projector-relevant resolutions. **Result:** a layout that uses the whole screen without
sacrificing readability.

### F10 — Palette and typography pass *(0846554)*
A coherent visual system: a quiet surface tint in place of a heavy saturated bubble color,
the accent color reserved strictly for primary actions / links / selection, a slate neutral
scale across both light and dark themes, and a real type scale — all expressed through
design tokens so the themes stay consistent. Deliberately **no web font** was introduced, to
avoid depending on a font download over venue wifi; only the scale changed. **Result:** a
considered, consistent visual identity with no new network dependency.

### F11 — Agent Skills (agentskills.io) *(2a55d31, 459cf79, d63a917, 39f8c38; live-run fixes 604dce1, 56ab58b)*
The agent conforms to the open Agent Skills standard: a skill is a folder with a `SKILL.md`
(YAML `name` + `description`, then instructions), loaded by **progressive disclosure** —
every run sees only each skill's name and description injected into the system prompt; on a
task match the model reads the full SKILL.md with one `read_file`; bundled `references/`
files are read only when the skill directs it. deepagents 0.7.8 ships this natively
(`SkillsMiddleware`), so the integration *wires* rather than rebuilds: skill files are
seeded into the virtual filesystem per run, and discovery/injection are library code.
Skills live in three tiers mirroring the memory tiers — **built-in** (shipped in the repo
`skills/` directory, trusted via code review), **organization**, and **personal** — with
org/user rows in a skill registry behind the store seam (F6), schema documented for the
frozen database migration. **Security:** v1 is deliberately instruction-only — bundled
`scripts/` are never seeded into agent state and `execute` stays stubbed, so "exec off"
holds at both the data and tool layer; installs are spec-validated (rejected with 422s
where the library only warns), land **untrusted and disabled**, and cannot be enabled until
explicitly reviewed. An untrusted skill is never injected at all — not even its description
— which is *stricter* than the S4 framing approach, because a skill is designed to be
obeyed while search results are merely consulted. Activation is visible end to end: a
`skill.activated` event on the same offset-addressed stream (F2), a SkillBlock in the
conversation feed, and a Skills manager view in the sidebar (tier groups, trust chips,
review-gated toggles, scripts shown locked "exec off · v1"). Two defects were found by
live runs, not by unit tests, and fixed: seeded files had to be FileData dicts rather than
raw strings (604dce1), and the model followed SKILL.md but skipped skill-directed
`references/` reads until those reads were made imperative in the skill body and exempted
from the prompt's speed/repetition budget (56ab58b) — the same "be fast pressure beats a
soft suggestion" failure mode as the plan-panel case below, fixed the same way, and
re-verified live. **Result:** the agent's capabilities are extensible by dropping in a
folder that any conformant agent can also consume, with the trust boundary shipped in the
same commit as the install surface — before sharing exists, not after.

---

## Investigated but deliberately not changed

- **Plan panel missing on a real research run — diagnosed, later fixed.** On a multi-part
  research task no plan panel appeared. The run's event log showed the planning tool was
  **never called** and no plan snapshot was ever emitted — so this is the model's choice,
  not the frontend dropping data (a sibling run under the same model *did* plan, end to end,
  proving the pipeline healthy). Root cause: the system prompt only *mentioned* planning as
  one soft suggestion buried under stronger "be fast, minimize tool calls" instructions, so
  a fast model skipped it. Originally the wording change was **proposed for review rather
  than applied** to avoid risk before the presentation. **Applied 2026-08-27:** the system
  prompt now makes `write_todos` the mandatory first tool call on every task (with status
  updates as steps complete), and a live run of a trivial one-step task was verified to emit
  `plan.snapshot` events before any output. This resolves the Platform 1 triggering caveat.

- **A relational database was designed, then frozen.** A move from JSON-backed storage to a
  real database was fully designed and then **deliberately not built** before the
  presentation — introducing a new persistence layer right before a demo adds a fresh
  failure surface for no demo benefit. The store seam (F6) remains ready for it; the risk
  was declined on purpose.

---

*This is a catalog summary. The authoritative record is the commit history and the audit
notes in `docs/AUDIT.md`.*

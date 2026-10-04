# Tests

The codebase's first tests — the verification scripts written during the audit
fixes and the frontend rewrite. They are a mix of standalone logic checks and
integration proofs that drive the live stack. All use the project `.venv`.

> Some proofs (`proof_kill_worker.py`, `proof_backend_restart.py`) hardcode the
> repo path `C:\Mukund's Projects\DeepAgent`; adjust if the repo moves.

## Tiers and how to run

Use the venv Python: `.venv\Scripts\python.exe`.

### 1. Standalone logic (no stack, no network)
Run from the repo root:
```
.venv\Scripts\python.exe tests\test_traversal.py      # artifact path-traversal containment
.venv\Scripts\python.exe tests\test_offset_dedup.py   # offset-vs-seq reducer dedup (the corruption fix)
```

### 2. Project-import unit tests (venv only, no live stack)
Run from the repo root with the repo on `PYTHONPATH`:
```
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe tests\test_registry.py     # atomic registry write + corrupt-JSON handling (isolated tmp dir)
.venv\Scripts\python.exe tests\test_concurrency.py  # per-run contextvars isolation (globals removed)
.venv\Scripts\python.exe tests\test_untrusted.py    # web_search <untrusted_web_content> framing
.venv\Scripts\python.exe tests\test_envelope.py     # v1 event-envelope mapping (all types, null identity fields)
.venv\Scripts\python.exe -m pytest tests\test_run_id.py  # run_id uniqueness suffix, slug bounds, legacy parsing, 409 on duplicate (#1)
.venv\Scripts\python.exe -m pytest tests\test_health.py  # GET /health via TestClient
```

### 2b. Auth / tenancy (venv only, no live stack, no Stytch network)
Standalone: each script builds an isolated FastAPI `TestClient` against a temp
`ARTIFACT_BASE`, fakes Temporal, and overrides `get_principal` per request
(shared setup in `auth_harness.py`, not a test). Dummy Stytch keys are set in
the harness, so no `.env` is needed. Run from the repo root:
```
.venv\Scripts\python.exe tests\test_idor.py        # B/other-org asking for A's thread/run/stream/artifact/skill -> 404, never 403, never data
.venv\Scripts\python.exe tests\test_forged_jwt.py  # real get_principal: missing/garbage/attacker-signed/wrong-project/expired JWT -> 401; valid -> Principal
.venv\Scripts\python.exe tests\test_org_scope.py   # org A's skills invisible to org B in the API listing AND the worker seed
.venv\Scripts\python.exe tests\test_admin_gate.py  # member cannot trust/enable/delete an org skill (403); admin can via network reverify; user-tier = ownership
.venv\Scripts\python.exe tests\test_quota.py       # N+1th run in a day for one org -> 429 + reset_at + Retry-After
.venv\Scripts\python.exe tests\test_flag_off.py    # AUTH_ENABLED=false: every endpoint behaves exactly pre-auth (no scoping/gate/quota/signing)
```
`test_forged_jwt.py` signs real RS256 JWTs with a throwaway keypair and swaps
the client's JWKS lookup + network fallback for in-process fakes, so it
exercises the real verification path deterministically. Env knobs the tests
touch: `AUTH_ENABLED`, `RUN_QUOTA_PER_ORG_PER_DAY`, `ARTIFACT_SIGNING_SECRET`.

### 3. Temporal-only (needs `temporal server start-dev` on :7233)
```
.venv\Scripts\python.exe tests\test_retry_offset.py  # real WorkflowStream: offsets unique across a forced retry
```

### 4. Real Gemini (needs GOOGLE_API_KEY; run from repo root)
```
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe tests\test_memory.py        # multi-turn recall, restart persistence, thread isolation
```

### 5. Full-stack integration proofs (need Temporal + worker + backend up)
Bring the stack up (see repo README), then run from the `tests\` directory so
the scripts find `sse_client.py`:
```
cd tests
..\.venv\Scripts\python.exe proof_smoke.py            # POST /runs -> SSE -> run.finished
..\.venv\Scripts\python.exe proof_resume.py           # refresh mid-run: Last-Event-ID resume, no dup
..\.venv\Scripts\python.exe proof_two_tabs.py         # two concurrent SSE readers, identical offsets
..\.venv\Scripts\python.exe proof_pastruns.py         # finished run replays from JSONL (watched)
..\.venv\Scripts\python.exe proof_noviewer.py         # finished run replays (never watched — background persister)
..\.venv\Scripts\python.exe proof_keepalive.py        # ': ping' every 15s on an idle stream
..\.venv\Scripts\python.exe proof_kill_worker.py      # kill worker mid-run -> retry streams cleanly (offset)
..\.venv\Scripts\python.exe proof_backend_restart.py  # restart backend mid-run -> re-attach persister, no truncation
..\.venv\Scripts\python.exe test_finished_replay.py   # finished-run replay characterization
```
Auth end-to-end (stack up with `AUTH_ENABLED=true` + real Stytch keys; run from the repo root):
```
.venv\Scripts\python.exe tests\proof_auth_live.py   # creates 2 QA orgs + 4 members in your Stytch Test project, mints real sessions, drives 4 real runs: IDOR 404s, signed artifacts, admin gate via real RBAC reverify, per-org worker seed, thread continuation, revocation, backfill
```
`sse_client.py` is the shared SSE/REST helper (not a test). `check_wf.py` is a
one-off workflow-status probe (edit the `WF` id).

## Frontend
`../frontend/tests/localstorage_degradation.ts` drives the real store against
hostile `localStorage` (corrupt / disabled / quota / absent). Build + run:
```
cd frontend
node_modules/.bin/esbuild tests/localstorage_degradation.ts --bundle --platform=node --format=esm --outfile=../artifacts/_degrade.mjs
node ../artifacts/_degrade.mjs
```

## Note
These began as one-shot verification scripts. The auth/skills suites
(`test_admin_gate`, `test_flag_off`, `test_forged_jwt`, `test_idor`,
`test_org_scope`, `test_quota`, `test_skills`), `test_registry`,
`test_run_id` and `test_health` are now also collected by `pytest`: each file is one test function that runs its
`check(...)` list and fails with every FAIL label in the assertion message
(the PASS/FAIL log is in captured stdout). `Harness()` resets shared module
state so they can run in any order in one process, and each still runs
standalone via `python tests\<file>.py`. `test_finished_replay` skips itself
under pytest when the backend is not up. The remaining module-level scripts,
a frontend test runner and CI are open items (see docs/HISTORY.md §8).

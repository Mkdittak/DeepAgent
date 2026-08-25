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
```

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
These began as one-shot verification scripts, not a CI suite — no test runner,
assertions are `print(... PASS/FAIL)`. Converting them to pytest + a frontend
test runner and wiring CI is Bucket-B work (see docs/AUDIT.md).

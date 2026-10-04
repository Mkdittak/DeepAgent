# DeepAgent — Running It

*Setup, start, auth setup, legacy data claim, troubleshooting. Endpoint and
env-var tables are in [REFERENCE.md](REFERENCE.md).*

---

## Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| Temporal CLI | latest | `temporal --version` |

Install the Temporal CLI with `scoop install temporal-cli` (Windows),
`brew install temporal` (macOS), or from https://docs.temporal.io/cli#install.

---

## 1. Configure

```bash
cp .env.example .env
```

Fill in the two required keys:

| Key | Get it from |
|---|---|
| `GOOGLE_API_KEY` | https://aistudio.google.com/apikey |
| `TAVILY_API_KEY` | https://app.tavily.com/home |

Everything else has a working default. Leave `AUTH_ENABLED=false` unless you
are setting up Stytch (§5).

> With auth off every visitor is the same implicit user and every
> conversation and file is visible to anyone who can reach the server. Keep
> the backend on loopback (the default) in this mode.

---

## 2. Install

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

`start.bat` looks for `.venv\Scripts\python.exe` and falls back to the system
`python` if it is missing.

---

## 3. Start

### One click (Windows)

Double-click `start.bat`. It opens four terminal windows, waits for each
service, and opens http://localhost:3000. Close the four windows to stop.

### Manually, four terminals

```
Terminal 1:  temporal server start-dev --db-filename .temporal.db
Terminal 2:  python -m temporal.worker
Terminal 3:  python -m backend.main
Terminal 4:  cd frontend && npm run dev
```

`--db-filename` matters. Without it the Temporal dev server is in-memory and
every workflow, including run history, is lost when it restarts.

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API | http://127.0.0.1:8000 |
| Temporal UI | http://localhost:8233 |

---

## 4. Use

Open http://localhost:3000 and type a request. Try:

| Prompt | Output |
|---|---|
| "Make a presentation on climate change" | `.pptx`, with the `slide-deck` skill activating |
| "Create a spreadsheet of top 10 countries by GDP" | `.xlsx` |
| "Build a landing page for a coffee shop" | `.html`, previewed inline |
| "Research the latest AI trends in 2026" | web search with live URLs, then a cited summary |

Watch the plan panel fill first, then tool blocks, then files. Send a
follow-up in the same thread and the agent remembers the earlier turn. Close
the tab mid-run and reopen: the run resumes where it was. Past conversations
are in the sidebar.

---

## 5. Optional: authentication and tenancy (Stytch B2B)

Auth is off by default. Turning it on gives per-member, per-organization
login, scoped data, admin-gated org skills, signed artifact links and a daily
run quota per org. Design and rationale are in [AUTH.md](AUTH.md).

### Stytch dashboard, one time, Test environment

1. Create a **B2B** project at https://stytch.com/dashboard and open **Test**.
2. **Authentication → Email Magic Links**: enable.
3. **Authentication → OAuth**: enable **Google** (Stytch's test credentials are fine).
4. **Redirect URLs**: add `http://localhost:3000/authenticate`, valid for
   **Login**, **Signup** and **Discovery**.
5. **RBAC**: under Resources add `org_skills` with action `manage`. Under
   Roles confirm `stytch_admin` has `org_skills: manage`. The org-skill
   trust/enable/delete routes check exactly this permission.
6. **API keys**: copy Project ID and a Secret for the backend, the Public
   token for the frontend.

### Backend `.env`

```env
AUTH_ENABLED=true
STYTCH_PROJECT_ID=project-test-...
STYTCH_SECRET=secret-test-...
STYTCH_ENV=test
ARTIFACT_SIGNING_SECRET=<any long random string>   # keeps artifact links valid across restarts
```

### Frontend `frontend/.env`

```env
VITE_STYTCH_PUBLIC_TOKEN=public-token-test-...
```

Restart the backend and the Vite dev server. The UI now shows a sign-in card.
Sign in with any email (magic link) or Google, create or pick an
organization. The first member of an org is its `stytch_admin`.

### Your pre-auth conversations

On the first start with the flag on, every row that has no owner is stamped
with the placeholder identity `legacy`/`legacy`. Nothing is lost, but nothing
is shown to anyone. To hand it to yourself:

1. Note your `organization_id` and `member_id` (dashboard → Organizations → members).
2. Stop the backend. It keeps the registry in memory and would overwrite the move.
3. Run:

```
.venv\Scripts\python.exe -m backend.claim_legacy --org organization-test-... --member member-test-... --unarchive
```

`--unarchive` also un-hides conversations that were archived when the sidebar
was introduced. `--dry-run` prints the counts without writing. Restart the
backend afterwards.

### Turning it off again

Set `AUTH_ENABLED=false`, blank `VITE_STYTCH_PUBLIC_TOKEN`, restart both. The
single-user app is back unchanged.

---

## 6. Tests and lint

```
pytest                       # unit + auth suites, no stack needed
ruff check . && ruff format --check .
```

Integration proofs that drive the live stack are listed in
[../tests/README.md](../tests/README.md).

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `temporal: command not found` | Install the Temporal CLI (Prerequisites) |
| `ModuleNotFoundError` | Activate the venv and run `pip install -e ".[dev]"` again |
| Frontend loads but nothing happens on Send | Backend (terminal 3) not running, or `VITE_API_BASE` points elsewhere. Check the browser console for the failed `POST /runs` |
| Blank page at localhost:3000 | `npm install` was not run in `frontend/` |
| API key errors in the worker window | `.env` keys missing or quoted. No quotes needed |
| Run starts but never streams | Worker (terminal 2) not running. Check the Temporal UI at :8233 for a workflow stuck in "Running" with no activity |
| Run ends with `GraphRecursionError` | Raise `AGENT_RECURSION_LIMIT` (default 30) |
| Past run shows "stream was interrupted by a backend restart" | Expected after a restart mid-run; the run finished on the server and the notice marks where the transcript may be incomplete |
| Runs vanish after restarting Temporal | You started it without `--db-filename` |
| Backend exits with `AUTH_ENABLED=true but STYTCH_PROJECT_ID / STYTCH_SECRET are not set` | Fill both keys, or set the flag to `false` |
| Login screen shows but every request is 401 | Backend keys belong to a different Stytch project than `VITE_STYTCH_PUBLIC_TOKEN` |
| Sign-in never completes after the email link | `http://localhost:3000/authenticate` is not registered for Discovery |
| Admin gets 403 trusting an org skill | RBAC resource `org_skills` / `manage` is not granted to `stytch_admin` |
| Artifact preview blank or download 404 with auth on | Signed link expired (60 s). Reopen. Set `ARTIFACT_SIGNING_SECRET` so links survive restarts |
| `429 daily run quota reached` | Wait for `reset_at` or raise `RUN_QUOTA_PER_ORG_PER_DAY` |
| Port already in use | Kill the process on that port |

---

## 8. Stopping

Close the four windows or `Ctrl+C` each terminal. Order does not matter.
Runs in flight keep going in Temporal if only the backend or frontend stops;
they resume streaming when the backend comes back.

# DeepAgent

An autonomous agent that turns one chat request into finished files
(presentations, spreadsheets, web pages), researched summaries or code, with
durable execution: close the tab, restart the server, the run finishes and
you can replay it.

> **Status:** proof of concept, single-process storage. See
> [docs/HISTORY.md](docs/HISTORY.md#8-open-items-and-roadmap) for what is open.

| Layer | Technology |
|---|---|
| Agent | LangChain Deep Agents on Gemini 3.6 Flash, Agent Skills (agentskills.io) |
| Execution | Temporal workflows, one activity per run |
| API | FastAPI, REST + Server-Sent Events |
| UI | React 19, TypeScript, Vite |
| Auth (optional) | Stytch B2B, behind `AUTH_ENABLED` |

---

## Quick start

Needs Python 3.11+, Node 20+ and the [Temporal CLI](https://docs.temporal.io/cli).

```bash
cp .env.example .env            # add GOOGLE_API_KEY and TAVILY_API_KEY
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

Then double-click `start.bat`, or in four terminals:

```
temporal server start-dev --db-filename .temporal.db
python -m temporal.worker
python -m backend.main
cd frontend && npm run dev
```

Open http://localhost:3000 and ask for a presentation on anything.

> Auth is off by default: every visitor is the same implicit user and every
> conversation is visible to anyone who can reach the server. Local use only
> in this mode. Turning Stytch on is in [docs/RUNNING.md §5](docs/RUNNING.md#5-optional-authentication-and-tenancy-stytch-b2b).

---

## What it does

- Plans first (visible todo panel), picks tools, streams every step live.
- Produces `.pptx`, `.xlsx` and `.html` files, previewed and downloadable in the chat.
- Web research with live URLs, results framed as untrusted data.
- Conversations with memory across turns; a sidebar of past threads.
- Skills: drop a `SKILL.md` folder into `skills/built-in/` or install org and
  personal skills through the UI with review-gated trust.
- Survives browser close, backend restart and worker crash without losing or
  duplicating a single event.
- Optional multi-tenant auth: per-member and per-organisation scoping, admin
  roles, signed artifact links, daily run quotas.

---

## Repository

```
agent/       create_agent, tools, skills seeding, per-run context
backend/     FastAPI routes, auth, thread + skill store, legacy claim CLI
temporal/    AgentWorkflow, run_deep_agent activity, worker
frontend/    React app: store, net (REST + SSE), components, auth
skills/      built-in Agent Skills (slide-deck, web-research)
tests/       pytest suites + live-stack proof scripts
docs/        the six documents below
start.bat    one-click launcher (Windows)
```

---

## Documentation

| Read this | For |
|---|---|
| [docs/RUNNING.md](docs/RUNNING.md) | setup, start, auth setup, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how it works: layers, event stream, worker, skills, threads, frontend, storage |
| [docs/REFERENCE.md](docs/REFERENCE.md) | every endpoint, env var, event type and id format |
| [docs/AUTH.md](docs/AUTH.md) | auth and tenancy design, rationale, demo walkthrough |
| [docs/STYTCH_NOTES.md](docs/STYTCH_NOTES.md) | the Stytch SDK surface, verified from installed source |
| [docs/HISTORY.md](docs/HISTORY.md) | mandates, timeline, every fix and feature, the audit, open items |
| [tests/README.md](tests/README.md) | how to run each test tier |

---

## License

Private. All rights reserved.

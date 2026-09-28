# DeepAgent

A general-purpose autonomous AI agent that handles any chat request — research, presentations, spreadsheets, landing pages, code execution — with durable execution guarantees.

> **Status:** Proof of Concept

---

## Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| AI        | LangChain Deep Agents, Gemini 3.5 Flash |
| Execution | Temporal (durable workflows)        |
| Backend   | FastAPI, WebSocket                  |
| Frontend  | React 19, TypeScript, Vite          |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- [Temporal CLI](https://docs.temporal.io/cli)

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

| Key              | Required | Get it from                            |
|------------------|----------|----------------------------------------|
| `GOOGLE_API_KEY` | Yes      | https://aistudio.google.com/apikey     |
| `TAVILY_API_KEY` | Yes      | https://app.tavily.com/home            |

> **Auth is off by default.** With `AUTH_ENABLED=false` every visitor is the same
> implicit user and every run, thread, and artifact is visible to anyone who can
> reach the server. This is intended for local development on your own machine
> only. Do not expose the backend on a network in this mode; see `docs/AUTH.md`
> for turning Stytch auth on.

### 2. Install

```bash
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

### 3. Run

**Option A** — Double-click `start.bat` (opens everything automatically)

**Option B** — Manual (4 terminals):

```
Terminal 1:  temporal server start-dev --db-filename .temporal.db
Terminal 2:  python -m temporal.worker
Terminal 3:  python -m backend.main
Terminal 4:  cd frontend && npm run dev
```

> **Note:** `--db-filename` persists Temporal state to disk. Without it, the dev
> server runs in-memory and loses all workflows (and run history) on restart.
> `start.bat` already passes this flag.

### 4. Open

Navigate to **http://localhost:3000** and send a message.

---

## What It Can Do

| Prompt | Output |
|--------|--------|
| *"Make a PPT on climate change"* | `.pptx` with formatted slides |
| *"Create a spreadsheet of top 10 countries by GDP"* | `.xlsx` with structured data |
| *"Build a landing page for a coffee shop"* | `.html` with styled content |
| *"Write a Python script for Fibonacci numbers"* | Code execution + output |
| *"Research the latest AI trends"* | Web search summary |

The agent autonomously plans, researches, generates files, and streams progress in real time.

---

## Project Structure

```
DeepAgent/
├── agent/                # AI agent core + tool implementations
│   ├── core.py           #   create_agent() setup + system prompt
│   └── tools.py          #   web_search, pptx, xlsx, html tools
│
├── temporal/             # Durable workflow orchestration
│   ├── workflows.py      #   AgentWorkflow definition
│   ├── activities.py     #   run_deep_agent activity
│   └── worker.py         #   Worker entry point
│
├── backend/              # FastAPI API server
│   └── main.py           #   WebSocket, health, artifacts, runs
│
├── frontend/             # React + TypeScript chat UI
│   └── src/
│       ├── App.tsx       #   Chat component
│       └── main.tsx      #   Entry point
│
├── docs/                 # Documentation
│   ├── ARCHITECTURE.md   #   System design & data flow
│   ├── HOW_TO_RUN.md     #   Detailed setup guide
│   └── MASTER_DOCUMENT.md#   Full project specification
│
├── artifacts/            # Generated output files (gitignored)
├── .env.example          # Environment template
├── pyproject.toml        # Python dependencies + tool config
└── start.bat             # One-click launcher (Windows)
```

---

## Architecture

```
React UI (3000) → FastAPI (8000) → Temporal (7233) → Deep Agent → Tools
                      ↑                                            │
                      └──── WebSocket streaming ◄── progress ──────┘
```

- **Temporal** ensures tasks survive browser/server restarts
- **WebSocket** streams real-time progress to the chat UI
- **Artifacts** are saved per-run and downloadable from the UI

---

## API

| Method | Endpoint                         | Description             |
|--------|----------------------------------|-------------------------|
| WS     | `/ws/chat`                       | Send message, stream progress |
| GET    | `/health`                        | Health check            |
| GET    | `/runs`                          | List all runs           |
| GET    | `/artifacts/{run_id}/{filename}` | Download generated file |

---

## Documentation

- **[How to Run](docs/HOW_TO_RUN.md)** — Detailed setup guide with troubleshooting
- **[Architecture](docs/ARCHITECTURE.md)** — System design and data flow
- **[Master Document](docs/MASTER_DOCUMENT.md)** — Full project specification

---

## License

Private — All rights reserved.

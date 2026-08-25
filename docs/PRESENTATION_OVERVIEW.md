# DeepAgent — Presentation Overview

> **One-liner:** An autonomous AI agent that takes a plain English request, plans and executes multi-step tasks, and delivers finished files — all through a chat interface.

---

## What Problem Does This Solve?

Today, getting AI to produce real deliverables (a PowerPoint, a spreadsheet, a web page) requires multiple manual steps: prompting, copying, formatting, re-prompting. **DeepAgent automates the entire pipeline.** You type one request, walk away, and come back to a finished file ready to download.

Key differentiators:
- **Fully autonomous** — the AI decides which tools to use, in what order, without hand-holding.
- **Crash-proof** — if your browser closes or the server restarts, the task keeps running. Reconnect anytime to see progress or download results.
- **General-purpose** — handles presentations, spreadsheets, web pages, web research, and code execution from the same chat box.

---

## Architecture at a Glance

```
   YOU (browser)
    |
    |  chat message
    v
 ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
 │  React UI    │────>│  FastAPI Server   │────>│  Temporal Engine  │
 │  (frontend)  │<────│  (backend)        │<────│  (orchestration)  │
 └──────────────┘     └──────────────────┘     └────────┬─────────┘
   port 3000            port 8000                        |
                                                         v
                                                  ┌──────────────┐
                                                  │  AI Agent     │
                                                  │  (Gemini LLM) │
                                                  │  + Tools      │
                                                  └──────────────┘
                                                    |  |  |  |
                                              Search PPTX XLSX HTML
```

**Four layers, each with a clear job:**

| Layer | What It Does | Tech |
|-------|-------------|------|
| **Frontend** | Chat UI, file downloads, reconnection | React 19, TypeScript, Vite |
| **Backend** | Routes messages, serves files, bridges UI to engine | FastAPI, WebSocket |
| **Orchestration** | Queues tasks, retries on failure, survives crashes | Temporal |
| **AI Agent** | Reasons about the request, picks tools, produces output | LangChain DeepAgents, Gemini 3.5 Flash |

---

## How a Request Flows End-to-End

> **Example:** User types *"Make a PowerPoint on climate change"*

1. **React** sends the message over a WebSocket to the backend.
2. **FastAPI** generates a unique run ID, starts a durable Temporal workflow.
3. **Temporal** queues the task; a worker picks it up.
4. The **AI Agent** receives the prompt, reasons about it, and decides to call `generate_pptx`.
5. The tool creates a `.pptx` file on disk.
6. Progress events stream back: Temporal -> FastAPI -> WebSocket -> React.
7. The user sees live status updates and a **download link** when the file is ready.

**If the browser closes mid-task:** Temporal keeps running. On reload, the UI auto-reconnects via a saved run ID and catches up on all missed events.

---

## File-by-File Breakdown

### Agent Layer — *The AI Brain* (`agent/`)

| File | What It Does | Key Point |
|------|-------------|-----------|
| **`core.py`** | Creates the autonomous agent with a system prompt and registers all tools. | This is where the LLM model is chosen (Gemini 3.5 Flash) and the agent's behavior is defined. The system prompt tells the agent to handle *any* request autonomously. |
| **`tools.py`** | Implements four custom tools the agent can call: `web_search`, `generate_pptx`, `generate_xlsx`, `generate_html`. | Each tool is a Python function decorated so the agent can invoke it by name. Files are saved to a per-run artifacts folder. |
| **`__init__.py`** | Standard Python module init — exports `create_agent` and the tool functions. | Wiring only; no logic. |

**How it connects:** The agent is created inside `activities.py` (Temporal layer) each time a task runs. The tools write files to disk that the backend later serves to the user.

---

### Temporal Layer — *Crash-Proof Execution* (`temporal/`)

| File | What It Does | Key Point |
|------|-------------|-----------|
| **`workflows.py`** | Defines `AgentWorkflow` — the durable wrapper around a single agent run. | Sets retry policy (3 attempts, exponential backoff), timeouts (15 min), and publishes a "done" event when finished. Uses `WorkflowStream` for real-time progress. |
| **`activities.py`** | Implements `run_deep_agent` — the activity that actually invokes the AI agent and streams progress events. | Creates the agent, iterates through its reasoning steps, and publishes events (`thinking`, `tool_call`, `artifact`, `done`) so the UI can show live updates. |
| **`worker.py`** | Entry point that starts a Temporal Worker process. | Connects to the Temporal server, registers the workflow and activity, and listens on the `"deep-agent-queue"` for tasks. |
| **`__init__.py`** | Module exports. | Wiring only. |

**How it connects:** The backend starts workflows via a Temporal client. The worker picks them up and runs the agent. Progress events flow back through `WorkflowStream` to the backend, which forwards them to the React UI.

---

### Backend Layer — *The API Bridge* (`backend/`)

| File | What It Does | Key Point |
|------|-------------|-----------|
| **`main.py`** | FastAPI server with 4 endpoints: health check, WebSocket chat, artifact downloads, and run listing. | The WebSocket endpoint is the heart — it starts Temporal workflows for new requests and reconnects to existing ones. It subscribes to the progress stream and forwards events to the browser in real time. Also maintains an in-memory registry of all runs. |
| **`__init__.py`** | Module exports. | Wiring only. |

**Endpoints at a glance:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness check |
| `/ws/chat` | WebSocket | Send a request, receive live progress events |
| `/artifacts/{run_id}/{filename}` | GET | Download a generated file |
| `/runs` | GET | List all past runs and their artifacts |

**How it connects:** Sits between the React frontend (WebSocket) and Temporal (gRPC client). Also serves files from the `artifacts/` directory.

---

### Frontend Layer — *The Chat UI* (`frontend/`)

| File | What It Does | Key Point |
|------|-------------|-----------|
| **`src/App.tsx`** | The entire chat interface — input box, message list, progress badges, artifact download links, past runs panel, and auto-reconnection logic. | Stores the active run ID in `localStorage` so it can auto-reconnect after a browser close. Color-coded badges show message types (user, status, progress, error). |
| **`src/main.tsx`** | React entry point — mounts the App component into the DOM. | Boilerplate only. |
| **`index.html`** | HTML shell with a `<div id="root">`. | Minimal; React takes over. |
| **`vite.config.ts`** | Dev server config — proxies `/ws` and `/artifacts` requests to the backend on port 8000. | Avoids CORS issues during development. |
| **`package.json`** | Dependencies (React 19, Vite 6, TypeScript 5.7) and build scripts. | `npm run dev` starts the dev server on port 3000. |
| **`tsconfig.json`** | TypeScript compiler settings. | Strict mode, ES2020 target. |

**How it connects:** Communicates exclusively through a WebSocket to the backend. Downloads artifacts via standard HTTP GET requests.

---

### Configuration & Launch Files (root)

| File | What It Does | Key Point |
|------|-------------|-----------|
| **`.env`** | Stores API keys (`GOOGLE_API_KEY`, `TAVILY_API_KEY`) and optional config. | **Never committed to Git.** Required for the agent and web search to work. |
| **`.env.example`** | Template showing which environment variables are needed. | Copy to `.env` and fill in your keys. |
| **`requirements.txt`** | Python dependencies with minimum versions. | Install with `pip install -r requirements.txt`. |
| **`start.bat`** | One-click Windows launcher — starts all 4 services in separate terminal windows and opens the browser. | Starts: Temporal server, Temporal worker, FastAPI backend, React frontend. |
| **`.gitignore`** | Excludes `.env`, `artifacts/`, `node_modules/`, `__pycache__/`, IDE files. | Keeps secrets and generated files out of the repo. |

---

## Key Technologies & Why They Were Chosen

| Technology | Role | Why This One? |
|-----------|------|---------------|
| **Temporal** | Durable task execution | Tasks survive crashes. Built-in retries, timeouts, and event streaming. No other framework offers this level of durability for long-running AI tasks. |
| **LangChain DeepAgents** | Autonomous agent framework | Provides the agent loop (reason -> act -> observe -> repeat) with built-in tool calling, task planning, and code execution. |
| **Google Gemini 3.5 Flash** | LLM model | Fast, capable, cost-effective for tool-calling workflows. |
| **FastAPI** | Web server | Native async/await, first-class WebSocket support, automatic API docs. |
| **React + Vite** | Frontend | Industry standard for reactive UIs; Vite gives sub-second hot reload. |
| **Tavily** | Web search API | Purpose-built for AI agents — returns clean, structured search results. |

---

## Resilience Features (What Makes This Production-Grade)

| Scenario | What Happens |
|----------|-------------|
| **Browser closes mid-task** | Task continues in Temporal. On reload, `localStorage` triggers auto-reconnect. |
| **Backend server restarts** | Temporal workflow is unaffected. Backend re-discovers runs from the `artifacts/` directory on startup. |
| **Agent hits an error** | Temporal retries the activity up to 3 times with exponential backoff (2s -> 4s -> 8s, max 30s). |
| **Network drops** | WebSocket closes gracefully. User can reconnect manually via "Past Runs" panel. |
| **Task takes a long time** | 15-minute timeout with 5-minute heartbeat interval ensures the system doesn't kill legitimate long tasks. |

---

## What the Agent Can Produce

| Output Type | Tool | Example Request |
|------------|------|-----------------|
| **PowerPoint** (.pptx) | `generate_pptx` | *"Make a presentation on Q3 sales results"* |
| **Excel** (.xlsx) | `generate_xlsx` | *"Create a spreadsheet comparing cloud providers"* |
| **Web Page** (.html) | `generate_html` | *"Build a landing page for our new product"* |
| **Research Summary** | `web_search` | *"Research the latest trends in AI agents"* |
| **Code + Files** | Built-in `execute` / `filesystem` | *"Write a Python script that cleans this CSV"* |

---

## Ports & Services Summary

| Service | Port | Started By |
|---------|------|-----------|
| React Frontend | `localhost:3000` | `npm run dev` |
| FastAPI Backend | `localhost:8000` | `python -m backend.main` |
| Temporal Server | `localhost:7233` | `temporal server start-dev` |
| Temporal Dashboard | `localhost:8233` | (auto, with Temporal server) |

---

## Future Roadmap (v2)

| Upgrade | What It Adds |
|---------|-------------|
| **PostgreSQL** | Replace in-memory run registry with persistent database — enables multiple backend instances. |
| **S3 Storage** | Replace local disk for artifacts — enables horizontal scaling and sharing. |
| **Vector Memory (pgvector)** | Agent remembers context across sessions — smarter over time. |
| **Kubernetes** | Containerize all services for cloud deployment and auto-scaling. |

---

## Talking Points for Your Presentation

1. **"It's one chat box that does everything."** — User types a request in plain English, the AI figures out the rest. No menus, no manual steps.

2. **"It doesn't break."** — Temporal guarantees that even if everything crashes, the task picks up where it left off. This is enterprise-grade reliability.

3. **"It's modular."** — Four clean layers (UI, API, orchestration, AI) that can be developed, tested, and scaled independently.

4. **"It's extensible."** — Adding a new capability (e.g., PDF generation) means writing one Python function in `tools.py` and registering it in `core.py`. The rest of the system handles it automatically.

5. **"The architecture scales."** — The v2 roadmap (Postgres, S3, K8s) takes this from a POC to a production deployment without rewriting anything.

---

*Document generated for internal presentation purposes.*

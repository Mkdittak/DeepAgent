# DeepAgent — How to Run (Step-by-Step Guide)

---

## What is DeepAgent?

DeepAgent is an autonomous AI agent platform that handles any chat request through a unified interface. It can generate **presentations (PPTX)**, **spreadsheets (XLSX)**, **landing pages (HTML)**, perform **web research**, and **execute code** — all via natural language.

**Stack:** LangChain Deep Agents + Temporal + FastAPI + React

---

## Prerequisites

| Requirement        | Version  | Check Command              |
|--------------------|----------|----------------------------|
| Python             | 3.11+    | `python --version`         |
| Node.js            | 20+      | `node --version`           |
| npm                | 9+       | `npm --version`            |
| Temporal CLI       | latest   | `temporal --version`       |
| Git (optional)     | any      | `git --version`            |

### Installing Temporal CLI

If you don't have the Temporal CLI installed:

```bash
# Windows (via Scoop)
scoop install temporal-cli

# macOS (via Homebrew)
brew install temporal

# Or download from: https://docs.temporal.io/cli#install
```

---

## Step 1 — Clone / Open the Project

```bash
cd "C:\Users\BVB School\Desktop\Mukund's Projects\DeepAgent"
```

---

## Step 2 — Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in the required API keys:

```env
GOOGLE_API_KEY=your-google-api-key-here       # Required — for Gemini 3.5 Flash
TAVILY_API_KEY=your-tavily-api-key-here        # Required — for web search
TEMPORAL_ADDRESS=localhost:7233                 # Optional — default shown
ARTIFACT_BASE=./artifacts                      # Optional — default shown
```

### Where to Get API Keys

| Key              | Where to Get It                              |
|------------------|----------------------------------------------|
| GOOGLE_API_KEY   | https://aistudio.google.com/apikey           |
| TAVILY_API_KEY   | https://app.tavily.com/home                  |

---

## Step 3 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **Tip:** Use a virtual environment to avoid conflicts:
> ```bash
> python -m venv venv
> venv\Scripts\activate       # Windows
> # source venv/bin/activate  # macOS/Linux
> pip install -r requirements.txt
> ```

---

## Step 4 — Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Step 5 — Start All 4 Services

### Option A — One-Click Start (Recommended)

Double-click **`start.bat`** in the project root. It will:
1. Open 4 separate terminal windows (one per service)
2. Wait for each service to initialize
3. Open `http://localhost:3000` in your browser automatically

> **Note:** No VS Code needed. Just double-click the file from File Explorer.

To stop everything, close the 4 terminal windows that were opened.

### Option B — Manual Start (4 Separate Terminals)

You need **4 separate terminals** running simultaneously. Open them all from the project root directory.

### Terminal 1 — Temporal Dev Server

```bash
temporal server start-dev
```

- Temporal Server runs on `localhost:7233`
- Dashboard UI at `http://localhost:8233`

### Terminal 2 — Temporal Worker

```bash
python -m temporal.worker
```

- Connects to Temporal Server
- Picks up and executes agent workflows

### Terminal 3 — FastAPI Backend

```bash
python -m backend.main
```

- API Server runs on `http://localhost:8000`
- WebSocket at `ws://localhost:8000/ws/chat`

### Terminal 4 — React Frontend

```bash
cd frontend
npm run dev
```

- Dev Server runs on `http://localhost:3000`
- Hot reload enabled

---

## Step 6 — Use the App

1. Open **http://localhost:3000** in your browser
2. Type a message in the chat input (e.g., *"Make a PPT on Amazon market sales"*)
3. Press Send
4. Watch real-time agent progress appear in the chat
5. Download generated files when the agent completes

---

## Quick-Start Summary (Cheat Sheet)

**Fastest way (after initial setup):**
```
Double-click start.bat → done.
```

**Manual way:**
```
Terminal 1:  temporal server start-dev
Terminal 2:  python -m temporal.worker
Terminal 3:  python -m backend.main
Terminal 4:  cd frontend && npm run dev
Browser:     http://localhost:3000
```

---

## Example Prompts to Try

| Prompt | Expected Output |
|--------|-----------------|
| "Make a presentation on climate change" | `.pptx` file with formatted slides |
| "Create a spreadsheet of top 10 countries by GDP" | `.xlsx` file with structured data |
| "Build a landing page for a coffee shop" | `.html` file with styled content |
| "Write a Python script for Fibonacci numbers" | Code execution + output in chat |
| "Research the latest AI trends in 2026" | Web search results summarized in chat |

---

## Project Structure Overview

```
DeepAgent/
├── agent/                  # AI Agent core + tools
│   ├── core.py             #   Agent creation, system prompt
│   └── tools.py            #   web_search, pptx, xlsx, html tools
│
├── temporal/               # Durable workflow orchestration
│   ├── workflows.py        #   AgentWorkflow definition
│   ├── activities.py       #   run_deep_agent activity + progress streaming
│   └── worker.py           #   Worker entry point
│
├── backend/                # FastAPI API server
│   └── main.py             #   WebSocket, health, artifacts, runs endpoints
│
├── frontend/               # React + TypeScript chat UI
│   └── src/
│       ├── main.tsx        #   React entry point
│       └── App.tsx         #   Chat component with reconnection logic
│
├── artifacts/              # Generated output files land here
├── .env                    # Your API keys (do not commit)
├── .env.example            # Template for .env
├── requirements.txt        # Python dependencies
└── README.md               # Original quick-start guide
```

---

## Architecture at a Glance

```
┌─────────────────────┐
│   React Chat UI      │  ← http://localhost:3000
│   (port 3000)        │
└────────┬────────────┘
         │ WebSocket
         ▼
┌─────────────────────┐
│   FastAPI Backend    │  ← http://localhost:8000
│   (port 8000)        │
└────────┬────────────┘
         │ Temporal Client
         ▼
┌─────────────────────┐
│   Temporal Server    │  ← localhost:7233 (dashboard: 8233)
│   (port 7233)        │
└────────┬────────────┘
         │ Workflow + Activity
         ▼
┌─────────────────────┐
│   Deep Agent Core    │  ← LangChain + Gemini 3.5 Flash
│   + Tools            │
└─────────────────────┘
    │       │       │       │
  Search   PPTX   XLSX    HTML
```

---

## Key Notes

### Why 4 Terminals?

Each service is a separate process:
- **Temporal Server** = the durable execution engine (like a task queue)
- **Temporal Worker** = the process that actually runs agent logic
- **FastAPI Backend** = the API layer between frontend and Temporal
- **React Frontend** = the user-facing chat interface

They communicate: **Frontend → Backend → Temporal → Worker → Agent → Tools**

### Durability & Resilience

- If your **browser crashes**, the agent keeps running in Temporal. Reopen the browser and it reconnects automatically (run ID is saved in localStorage).
- If the **backend restarts**, in-progress workflows survive in Temporal and can be re-subscribed.
- Temporal retries failed activities up to **3 times** with exponential backoff.

### Artifacts

- All generated files (`.pptx`, `.xlsx`, `.html`) are saved to `./artifacts/{run_id}/`
- Each run gets a human-readable ID like `make-a-ppt-on-amazon_2026-07-29_14-30`
- Files are downloadable from the chat UI or via `GET /artifacts/{run_id}/{filename}`

### Ports Summary

| Service          | Port  | URL                            |
|------------------|-------|--------------------------------|
| React Frontend   | 3000  | http://localhost:3000          |
| FastAPI Backend   | 8000  | http://localhost:8000          |
| Temporal Server  | 7233  | localhost:7233                 |
| Temporal Dashboard| 8233 | http://localhost:8233           |

### API Endpoints

| Method | Endpoint                          | Purpose                      |
|--------|-----------------------------------|------------------------------|
| WS     | `/ws/chat`                        | Send messages, receive progress |
| GET    | `/health`                         | Health check                 |
| GET    | `/runs`                           | List all runs with metadata  |
| GET    | `/artifacts/{run_id}/{filename}`  | Download a generated file    |

### AI Model Used

- **Google Gemini 3.5 Flash** (`google_genai:gemini-3.5-flash`) — fast and capable
- Configured in `agent/core.py`
- To change the model, update the model string in `core.py`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `temporal: command not found` | Install Temporal CLI (see Prerequisites) |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| WebSocket connection refused | Make sure the FastAPI backend (Terminal 3) is running |
| Blank page at localhost:3000 | Make sure `npm install` was run in `frontend/` |
| API key errors | Check `.env` file has valid keys (no quotes needed) |
| Port already in use | Kill the process using that port or change the port |
| Agent times out | Check Temporal dashboard at http://localhost:8233 for workflow status |

---

## Stopping the App

Press `Ctrl+C` in each of the 4 terminal windows to stop the services. Order doesn't matter, but stopping Temporal last is cleanest.

---

*Document generated for DeepAgent POC — Last updated: July 29, 2026*

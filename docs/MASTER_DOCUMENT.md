# DeepAgent — Complete Project Documentation

> **A General-Purpose Autonomous AI Agent Platform**
> Built with LangChain Deep Agents, Temporal, FastAPI, and React

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Does This Project Do?](#2-what-does-this-project-do)
3. [Architecture Overview](#3-architecture-overview)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [Complete Code Walkthrough](#6-complete-code-walkthrough)
   - 6.1 [Agent Layer — The AI Brain](#61-agent-layer--the-ai-brain)
   - 6.2 [Temporal Layer — Durable Execution](#62-temporal-layer--durable-execution)
   - 6.3 [Backend Layer — API Server](#63-backend-layer--api-server)
   - 6.4 [Frontend Layer — User Interface](#64-frontend-layer--user-interface)
   - 6.5 [Configuration Files](#65-configuration-files)
7. [End-to-End Request Flow](#7-end-to-end-request-flow)
8. [Setup & Running Instructions](#8-setup--running-instructions)
9. [Key Design Decisions](#9-key-design-decisions)
10. [Future Roadmap (v2)](#10-future-roadmap-v2)

---

## 1. Executive Summary

**DeepAgent** is an autonomous AI agent platform that can handle any user request — from generating PowerPoint presentations, to building spreadsheets, creating landing pages, and performing live web research — all through a simple chat interface.

**What makes it special:**
- **Autonomous** — The AI plans and executes multi-step tasks on its own, choosing the right tools without user intervention.
- **Durable** — Powered by Temporal, tasks survive browser crashes, server restarts, and network failures. Close your tab and come back later — your task is still running.
- **Real-time** — Users see live progress as the agent works (planning, researching, generating files).
- **Extensible** — Adding new capabilities (e.g., PDF generation, database queries) requires only adding a new tool function.

---

## 2. What Does This Project Do?

A user opens the web interface, types a request like *"Make a PPT on Amazon market sales"*, and the system:

1. **Plans** the task — breaks it into steps (research, organize data, build slides)
2. **Researches** — searches the web for up-to-date information using the Tavily API
3. **Generates** — creates the requested output (PowerPoint, Excel, HTML page, etc.)
4. **Streams progress** — shows each step live in the chat UI
5. **Delivers** — provides a download link for the finished file

All of this happens autonomously. The user just sends one message and waits.

### Supported Output Types

| Output | Tool Used | File Produced |
|--------|-----------|---------------|
| Presentations | `generate_pptx` | `presentation.pptx` |
| Spreadsheets | `generate_xlsx` | `results.xlsx` |
| Landing Pages | `generate_html` | `index.html` |
| Research | `web_search` | Text response in chat |
| Code/Scripts | Built-in `execute` | Inline results |

---

## 3. Architecture Overview

The system is built as a **three-tier architecture** with a durable execution layer:

```
┌─────────────────────────────────────────────────────────────┐
│                    REACT CHAT UI                            │
│                    (frontend/)                              │
│                                                             │
│  - User types a message and hits Send                       │
│  - Connects to backend via WebSocket                        │
│  - Displays real-time progress (planning, tool calls, etc.) │
│  - Shows download links for generated files                 │
│  - Auto-reconnects if page is reloaded                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ WebSocket (ws://localhost:8000/ws/chat)
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    FASTAPI SERVER                            │
│                    (backend/)                                │
│                                                             │
│  - Receives user messages over WebSocket                    │
│  - Starts a Temporal workflow for each request               │
│  - Subscribes to workflow progress events                    │
│  - Forwards progress events back to the browser              │
│  - Serves generated files for download                       │
│  - Thin layer — contains NO AI logic                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ Temporal Client SDK
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    TEMPORAL                                   │
│                    (temporal/)                                │
│                                                             │
│  - One workflow per user request (AgentWorkflow)             │
│  - Runs the AI agent as an "activity"                        │
│  - Provides durability: retries, persistence, crash recovery │
│  - Streams progress events via WorkflowStream                │
│  - If the process crashes, Temporal reruns the activity       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ Activity invokes agent
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    DEEP AGENT (AI)                            │
│                    (agent/)                                   │
│                                                             │
│  - Powered by Google Gemini 3.5 Flash                        │
│  - System prompt defines behavior and guidelines             │
│  - Custom tools: web_search, generate_pptx/xlsx/html         │
│  - Built-in tools: write_todos, filesystem, execute, task    │
│  - Plans autonomously, picks tools, produces output          │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **AI Model** | Google Gemini 3.5 Flash | LLM that powers the autonomous agent |
| **Agent Framework** | LangChain Deep Agents | Wraps the LLM with tool-use and planning capabilities |
| **Workflow Engine** | Temporal | Durable execution — retries, crash recovery, persistence |
| **Backend API** | FastAPI (Python) | WebSocket server, artifact serving, Temporal orchestration |
| **Frontend** | React 19 + TypeScript | Chat UI with real-time streaming |
| **Build Tool** | Vite 6 | Fast frontend development server and bundler |
| **Web Search** | Tavily API | Real-time web search for the agent |
| **File Generation** | python-pptx, openpyxl | PowerPoint and Excel file creation |

### Python Dependencies (`pyproject.toml`)

```
fastapi>=0.115.0          # Web framework for the API server
uvicorn[standard]>=0.32.0 # ASGI server to run FastAPI
websockets>=14.0          # WebSocket protocol support

deepagents>=0.6.0         # LangChain Deep Agents framework
langchain-anthropic>=0.4.0 # LangChain Anthropic integration

temporalio>=1.10.0        # Temporal SDK for Python

tavily-python>=0.5.0      # Tavily web search API client
python-pptx>=1.0.0        # PowerPoint file generation
openpyxl>=3.1.0           # Excel file generation

python-dotenv>=1.0.0      # Load .env files for configuration
```

### Frontend Dependencies (`frontend/package.json`)

```
react: ^19.0.0            # UI library
react-dom: ^19.0.0        # React DOM renderer
typescript: ^5.7.0        # Type-safe JavaScript
vite: ^6.0.0              # Build tool and dev server
@vitejs/plugin-react      # React support for Vite
```

---

## 5. Project Structure

```
DeepAgent/
│
├── agent/                          # AI AGENT LAYER
│   ├── __init__.py                 #   Module exports
│   ├── core.py                     #   Agent creation + system prompt
│   └── tools.py                    #   Tool implementations (search, pptx, xlsx, html)
│
├── temporal/                       # DURABLE EXECUTION LAYER
│   ├── __init__.py                 #   Module marker
│   ├── workflows.py                #   AgentWorkflow definition
│   ├── activities.py               #   run_deep_agent activity + progress streaming
│   └── worker.py                   #   Worker process entry point
│
├── backend/                        # API SERVER LAYER
│   ├── __init__.py                 #   Module marker
│   └── main.py                     #   FastAPI app (WebSocket, health, artifacts)
│
├── frontend/                       # USER INTERFACE LAYER
│   ├── index.html                  #   HTML shell
│   ├── package.json                #   Node.js dependencies
│   ├── tsconfig.json               #   TypeScript compiler config
│   ├── vite.config.ts              #   Vite build/dev config
│   └── src/
│       ├── main.tsx                #   React entry point
│       └── App.tsx                 #   Chat UI component
│
├── artifacts/                      # GENERATED OUTPUT FILES
│   └── {run-name}_{timestamp}/     #   One folder per run (e.g., make-a-ppt-on-amazon_2026-07-24_14-30-05/)
│       ├── presentation.pptx       #     Generated PowerPoint
│       ├── results.xlsx            #     Generated spreadsheet
│       └── index.html              #     Generated landing page
│
├── .env                            # Environment variables (API keys — NOT committed)
├── .env.example                    # Template for .env
├── pyproject.toml                  # Python dependencies + tool config
├── README.md                       # Quick-start guide
└── ARCHITECTURE.md                 # Architecture design document
```

---

## 6. Complete Code Walkthrough

Every file in the project is explained below, with line-by-line annotations.

---

### 6.1 Agent Layer — The AI Brain

This layer defines the AI agent: what model it uses, what instructions it follows, and what tools it has access to.

---

#### `agent/__init__.py` — Module Exports

```python
from agent.core import create_agent
from agent.tools import web_search, generate_pptx, generate_xlsx, generate_html

__all__ = ["create_agent", "web_search", "generate_pptx", "generate_xlsx", "generate_html"]
```

**Purpose:** Makes this folder a Python package and exports the key functions so other parts of the codebase can do `from agent import create_agent`.

- **Line 1:** Imports the `create_agent` factory function from `core.py`.
- **Line 2:** Imports all four tool functions from `tools.py`.
- **Line 4:** `__all__` defines what gets exported when someone does `from agent import *`.

---

#### `agent/core.py` — Agent Creation & System Prompt

```python
"""
Core Deep Agent setup — one general-purpose agent with broad capabilities.
"""

from deepagents import create_deep_agent

from agent.tools import web_search, generate_pptx, generate_xlsx, generate_html

SYSTEM_PROMPT = """\
You are a general-purpose autonomous agent. You can handle ANY user request:
research topics, write code, create presentations, build spreadsheets, generate
landing pages, and more.

Guidelines:
- Plan before acting: use write_todos to break complex tasks into steps.
- Pick the right tool for each step — don't ask the user which tool to use.
- For presentations: use the generate_pptx tool with a title and slide data.
- For spreadsheets: use the generate_xlsx tool with headers and row data.
- For landing pages: use the generate_html tool with title and body HTML.
- For research: use the web_search tool to find current information.
- You can also use the built-in filesystem and execute tools for code tasks.
- Be thorough but concise. Deliver complete, usable output.
"""


def create_agent():
    """Create and return the configured Deep Agent."""
    return create_deep_agent(
        model="google_genai:gemini-3.5-flash",
        system_prompt=SYSTEM_PROMPT,
        tools=[
            web_search,
            generate_pptx,
            generate_xlsx,
            generate_html,
        ],
        # Built-in tools (write_todos, filesystem, execute, task) are included
        # automatically by Deep Agents.
    )
```

**Purpose:** This is the "brain configuration" file. It defines what the AI agent knows, how it behaves, and what tools it can use.

**Line-by-line breakdown:**

- **Line 5 (`from deepagents import create_deep_agent`):** Imports the Deep Agents framework factory function. This is the core library that wraps an LLM with autonomous planning and tool-use capabilities.
- **Line 7:** Imports our four custom tools so we can register them with the agent.
- **Lines 9–23 (`SYSTEM_PROMPT`):** The system prompt is the set of instructions that tells the AI how to behave. Key rules:
  - It should **plan before acting** using the `write_todos` built-in tool.
  - It should **autonomously pick tools** — never ask the user which tool to use.
  - It maps request types to specific tools (PPT → `generate_pptx`, etc.).
- **Lines 27–39 (`create_agent()`):** Factory function that creates a new agent instance:
  - **`model="google_genai:gemini-3.5-flash"`** — Uses Google's Gemini 3.5 Flash model as the LLM.
  - **`system_prompt=SYSTEM_PROMPT`** — Injects the behavioral instructions.
  - **`tools=[...]`** — Registers our four custom tools. The agent also automatically gets built-in tools like `write_todos`, `filesystem`, `execute`, and `task` from the Deep Agents framework.

---

#### `agent/tools.py` — Tool Implementations

This file contains the four custom tools the agent can invoke. Each tool is a plain Python function — the Deep Agents framework automatically wraps them for the AI to call.

```python
"""
Tool implementations for the Deep Agent.
Each tool is a plain function — Deep Agents auto-wraps them.
"""

import json
import os

from tavily import TavilyClient
```

- **Lines 6–7:** Standard library imports for JSON handling and environment variables.
- **Line 9:** Imports the Tavily client for web search functionality.

##### Tool 1: Web Search

```python
def web_search(query: str) -> str:
    """Search the web for up-to-date information on any topic.

    Args:
        query: The search query string.

    Returns:
        A JSON string with a list of search results (title, url, snippet).
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "TAVILY_API_KEY not set"})
    client = TavilyClient(api_key=api_key)
    results = client.search(query, max_results=5)
    return json.dumps(results.get("results", []), indent=2)
```

**What it does:** Searches the internet for real-time information. The agent calls this when it needs current data (market stats, company info, news).

- **Line 16:** Function signature — takes a search query string, returns JSON string. The docstring serves double duty: it's both Python documentation AND the description the AI reads to decide when to use this tool.
- **Line 25:** Reads the Tavily API key from environment variables.
- **Lines 26–27:** Graceful error handling if the API key isn't configured.
- **Line 28:** Creates a Tavily API client.
- **Line 29:** Performs the search, limited to 5 results for conciseness.
- **Line 30:** Returns the results as formatted JSON for the AI to read and incorporate.

##### Tool 2: PowerPoint Generation

```python
def generate_pptx(title: str, slides: list[dict]) -> str:
    """Create a PowerPoint presentation and save it as presentation.pptx.

    Args:
        title: The presentation title for the title slide.
        slides: A list of dicts, each with 'title' (str) and 'bullets' (list[str]).

    Returns:
        The file path of the generated .pptx file.
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()

    # Title slide
    slide_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title
    if slide.placeholders[1]:
        slide.placeholders[1].text = "Generated by DeepAgent"

    # Content slides
    for s in slides:
        slide_layout = prs.slide_layouts[1]  # Title + Content
        slide = prs.slides.add_slide(slide_layout)
        slide.shapes.title.text = s.get("title", "Slide")
        body = slide.placeholders[1]
        tf = body.text_frame
        tf.clear()
        for i, bullet in enumerate(s.get("bullets", [])):
            if i == 0:
                tf.text = bullet
            else:
                p = tf.add_paragraph()
                p.text = bullet
                p.level = 0

    output_dir = os.environ.get("ARTIFACT_DIR", "./artifacts")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "presentation.pptx")
    prs.save(path)
    return f"Saved presentation to {path}"
```

**What it does:** Creates a real `.pptx` PowerPoint file from structured data.

- **Lines 37–43:** Function signature. The AI calls this with a `title` and a list of `slides`, where each slide has a `title` and `bullets` list.
- **Lines 47–48:** Lazy imports of `python-pptx` library (only loaded when actually needed).
- **Line 50:** Creates a new blank PowerPoint presentation object.
- **Lines 52–57:** Creates the **title slide** using PowerPoint's first layout template (index 0). Sets the main title and subtitle ("Generated by DeepAgent").
- **Lines 59–73:** Iterates through each slide dict to create **content slides**:
  - Uses layout index 1 (Title + Content layout).
  - Sets the slide title from `s["title"]`.
  - Fills the body text frame with bullet points.
  - The first bullet is set directly (`tf.text`), subsequent bullets are added as new paragraphs.
- **Lines 75–79:** Saves the file:
  - Reads `ARTIFACT_DIR` from environment (set by the Temporal activity per run).
  - Creates the directory if it doesn't exist.
  - Saves as `presentation.pptx` and returns the file path.

##### Tool 3: Excel Spreadsheet Generation

```python
def generate_xlsx(title: str, headers: list[str], rows: list[list]) -> str:
    """Create an Excel spreadsheet and save it as results.xlsx.

    Args:
        title: The worksheet title / name.
        headers: Column header strings.
        rows: List of row data (each row is a list of cell values).

    Returns:
        The file path of the generated .xlsx file.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = title

    # Headers in bold
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    # Data rows
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    output_dir = os.environ.get("ARTIFACT_DIR", "./artifacts")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "results.xlsx")
    wb.save(path)
    return f"Saved spreadsheet to {path}"
```

**What it does:** Creates a real `.xlsx` Excel file with headers and data rows.

- **Lines 97–98:** Lazy imports of `openpyxl` library.
- **Lines 100–102:** Creates a new workbook with a single active worksheet, named per the `title` parameter.
- **Lines 104–107:** Writes **bold headers** in row 1.
- **Lines 109–112:** Fills in **data rows** starting from row 2.
- **Lines 114–118:** Saves to `ARTIFACT_DIR/results.xlsx`.

##### Tool 4: HTML Landing Page Generation

```python
def generate_html(title: str, body_html: str) -> str:
    """Create an HTML landing page and save it as index.html.

    Args:
        title: The page <title> and visible heading.
        body_html: The HTML content for the page body (can include tags).

    Returns:
        The file path of the generated .html file.
    """
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 800px;
               margin: 2rem auto; padding: 0 1rem; line-height: 1.6;
               color: #333; }}
        h1 {{ color: #1a1a2e; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {body_html}
</body>
</html>"""

    output_dir = os.environ.get("ARTIFACT_DIR", "./artifacts")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return f"Saved landing page to {path}"
```

**What it does:** Creates a styled HTML landing page.

- **Lines 136–150:** Builds a complete HTML document using an f-string template. Includes responsive CSS styling (centered layout, system font, clean typography).
- **Lines 152–157:** Writes the HTML file to `ARTIFACT_DIR/index.html`.

---

### 6.2 Temporal Layer — Durable Execution

Temporal is what makes this system **production-grade**. It ensures that agent runs survive crashes, retries on failure, and can be monitored. Without Temporal, a browser close or server crash would kill a running task.

---

#### `temporal/workflows.py` — Workflow Definition

```python
"""
Temporal workflow: one workflow per user chat request.
Uses WorkflowStream to publish agent progress events that the
FastAPI layer subscribes to.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib.workflow_streams import WorkflowStream

# Activity import is deferred via sandbox-safe import
with workflow.unsafe.imports_passed_through():
    from temporal.activities import run_deep_agent, AgentInput, AgentProgress


@dataclass
class WorkflowInput:
    """Input to the agent workflow."""
    run_id: str
    user_message: str


@workflow.defn
class AgentWorkflow:
    """Wraps a single Deep Agent run as a durable Temporal workflow."""

    @workflow.init
    def __init__(self, input: WorkflowInput) -> None:
        self.stream = WorkflowStream()
        self.progress_topic = self.stream.topic("progress", type=AgentProgress)
        self.done = False
        self.result: str | None = None

    @workflow.run
    async def run(self, input: WorkflowInput) -> str:
        """Execute the Deep Agent via an activity and stream progress."""
        result = await workflow.execute_activity(
            run_deep_agent,
            AgentInput(run_id=input.run_id, user_message=input.user_message),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=3,
            ),
        )
        # Publish final "done" event
        self.progress_topic.publish(AgentProgress(
            step="done",
            detail=result,
            artifacts=[],
        ))
        self.done = True
        self.result = result
        return result

    @workflow.query
    def is_done(self) -> bool:
        return self.done

    @workflow.query
    def get_result(self) -> str | None:
        return self.result
```

**Purpose:** Defines the durable workflow that wraps each agent run.

**Key concepts:**

- **Line 15 (`with workflow.unsafe.imports_passed_through()`):** Temporal runs workflows in a sandboxed environment for determinism. This line tells Temporal to pass through the activity imports without sandboxing them (needed because activities use non-deterministic I/O).
- **Lines 19–22 (`WorkflowInput`):** A dataclass that defines the input to the workflow — a `run_id` (unique identifier) and the `user_message` (the user's prompt).
- **Lines 25–26 (`@workflow.defn`):** Marks this class as a Temporal workflow definition.
- **Lines 29–34 (`__init__`):** Called when the workflow starts:
  - Creates a `WorkflowStream` — a pub/sub mechanism for streaming events out of the workflow.
  - Creates a `progress` topic that publishes `AgentProgress` events.
  - Initializes `done` and `result` tracking variables.
- **Lines 37–57 (`run`):** The main workflow method:
  - **`execute_activity`** — Runs the `run_deep_agent` activity (the actual AI agent call).
  - **`start_to_close_timeout=15min`** — The activity has up to 15 minutes to complete.
  - **`heartbeat_timeout=5min`** — The activity must send a heartbeat at least every 5 minutes (if it stops heartbeating, Temporal assumes it crashed and retries).
  - **`retry_policy`** — If the activity fails, Temporal retries up to 3 times with exponential backoff (2s → 30s).
  - After the activity completes, publishes a final `"done"` event.
- **Lines 59–65 (`is_done`, `get_result`):** Query handlers that let external code check the workflow's status without affecting its execution.

---

#### `temporal/activities.py` — Agent Activity & Progress Streaming

```python
"""
Temporal activity: invokes the Deep Agent and publishes streaming progress.
"""

import os
import json
from dataclasses import dataclass, field

from temporalio import activity
from temporalio.contrib.workflow_streams import WorkflowStreamClient


@dataclass
class AgentInput:
    run_id: str
    user_message: str


@dataclass
class AgentProgress:
    step: str          # e.g. "planning", "tool_call", "result", "done"
    detail: str        # human-readable description
    artifacts: list[str] = field(default_factory=list)  # filenames produced


@activity.defn
async def run_deep_agent(input: AgentInput) -> str:
    """
    Run the Deep Agent for a user message. Publishes progress events via
    WorkflowStream so the FastAPI layer can forward them to the client.
    """
    # Set artifact directory per run
    artifact_dir = os.path.join(
        os.environ.get("ARTIFACT_BASE", "./artifacts"),
        input.run_id,
    )
    os.makedirs(artifact_dir, exist_ok=True)
    os.environ["ARTIFACT_DIR"] = artifact_dir

    # Connect to the workflow stream to publish progress
    stream_client = WorkflowStreamClient.from_within_activity()
    async with stream_client:
        progress = stream_client.topic("progress", type=AgentProgress)

        progress.publish(AgentProgress(
            step="starting",
            detail=f"Processing: {input.user_message}",
        ))

        # Create and invoke the agent
        from agent.core import create_agent
        agent = create_agent()

        progress.publish(AgentProgress(
            step="planning",
            detail="Agent is planning the approach...",
        ))

        # Stream the agent execution
        last_tool_name = ""
        final_response = ""

        activity.heartbeat("invoking agent")

        try:
            async for event in agent.astream(
                {"messages": [{"role": "user", "content": input.user_message}]},
                stream_mode="updates",
            ):
                activity.heartbeat("processing")

                # Extract meaningful events to publish
                for node_name, node_data in (
                    event.items() if isinstance(event, dict) else []
                ):
                    if node_name == "agent" and "messages" in node_data:
                        for msg in node_data["messages"]:
                            content = getattr(msg, "content", "")
                            if isinstance(content, str) and content.strip():
                                final_response = content.strip()
                                progress.publish(AgentProgress(
                                    step="thinking",
                                    detail=content[:200],
                                ))
                            # Check for tool calls
                            tool_calls = getattr(msg, "tool_calls", [])
                            for tc in tool_calls:
                                tool_name = (
                                    tc.get("name", "")
                                    if isinstance(tc, dict)
                                    else getattr(tc, "name", "")
                                )
                                if tool_name and tool_name != last_tool_name:
                                    last_tool_name = tool_name
                                    progress.publish(AgentProgress(
                                        step="tool_call",
                                        detail=f"Using tool: {tool_name}",
                                    ))

                    elif node_name == "tools" and "messages" in node_data:
                        for msg in node_data["messages"]:
                            content = getattr(msg, "content", "")
                            if isinstance(content, str) and content.strip():
                                # Check if a file was produced
                                artifacts = []
                                for ext in [".pptx", ".xlsx", ".html"]:
                                    if ext in content:
                                        fname = (
                                            content.split(ext)[0]
                                            .split("/")[-1]
                                            .split("\\")[-1]
                                            + ext
                                        )
                                        artifacts.append(fname)
                                if artifacts:
                                    progress.publish(AgentProgress(
                                        step="artifact",
                                        detail=f"Produced: {', '.join(artifacts)}",
                                        artifacts=artifacts,
                                    ))
        except Exception as e:
            # If we already produced artifacts, treat as success with a note
            activity.heartbeat("handling post-tool error")

        # List final artifacts
        produced = []
        if os.path.isdir(artifact_dir):
            produced = os.listdir(artifact_dir)
        if produced:
            progress.publish(AgentProgress(
                step="result",
                detail=f"Completed. Files: {', '.join(produced)}",
                artifacts=produced,
            ))

    return final_response or f"Task completed. Artifacts in {artifact_dir}: {produced}"
```

**Purpose:** This is the bridge between Temporal and the AI agent. It runs the agent and publishes real-time progress events.

**Key sections:**

- **Lines 13–23 (`AgentInput`, `AgentProgress`):** Data structures:
  - `AgentInput` — What the activity receives (run ID + user message).
  - `AgentProgress` — Progress event structure with a step type, human-readable detail, and list of artifact filenames.
- **Lines 26–38 (Setup):** Prepares the run:
  - Creates a unique artifact directory for this run (e.g., `artifacts/make-a-ppt-on-amazon_2026-07-24/`).
  - Sets the `ARTIFACT_DIR` environment variable so the tools know where to save files.
- **Lines 40–48 (Stream setup):** Connects to the Temporal WorkflowStream to publish progress events that the FastAPI server will forward to the browser.
- **Lines 50–56 (Agent creation):** Creates the AI agent (lazy import to avoid loading heavy ML libraries until needed) and publishes "planning" status.
- **Lines 58–109 (Agent execution loop):** The core execution:
  - **`agent.astream(..., stream_mode="updates")`** — Runs the AI agent in streaming mode, receiving events as the agent thinks and acts.
  - **Agent events (lines 74–92):** When the agent produces thinking text or makes tool calls, we extract that info and publish it as progress events.
  - **Tool events (lines 94–109):** When tools produce output, we check if files were created (by looking for `.pptx`, `.xlsx`, `.html` extensions) and publish artifact notifications.
  - **`activity.heartbeat("processing")`** — Tells Temporal "I'm still alive" to prevent timeout.
- **Lines 110–125 (Cleanup):** Lists all files in the artifact directory and publishes a final "result" event.

---

#### `temporal/worker.py` — Worker Process

```python
"""
Temporal worker — run this process to pick up agent workflows.

Usage:
    python -m temporal.worker
"""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from temporal.workflows import AgentWorkflow
from temporal.activities import run_deep_agent

TASK_QUEUE = "deep-agent-queue"


async def main():
    temporal_address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    print(f"Connecting to Temporal at {temporal_address}...")

    client = await Client.connect(temporal_address)
    print(f"Starting worker on task queue: {TASK_QUEUE}")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentWorkflow],
        activities=[run_deep_agent],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

**Purpose:** This is the process that actually executes workflows. Think of it as a "job runner" — it connects to the Temporal server, says "I can run `AgentWorkflow` and `run_deep_agent`", and waits for work.

- **Line 17 (`TASK_QUEUE`):** All workflows and activities communicate through this named queue. The backend puts work on the queue; the worker picks it up.
- **Lines 20–25:** Connects to the Temporal server (default: `localhost:7233`).
- **Lines 27–33:** Creates a `Worker` that registers:
  - **Workflows:** `AgentWorkflow` — the workflow class it can execute.
  - **Activities:** `run_deep_agent` — the activity function it can run.
- **Line 33 (`await worker.run()`):** Starts the worker in an infinite loop, polling for new tasks.

---

### 6.3 Backend Layer — API Server

The backend is a thin orchestration layer — it doesn't contain any AI logic. Its job is to connect the browser to Temporal and serve files.

---

#### `backend/main.py` — FastAPI Application

```python
"""
FastAPI server — thin interface between React UI and Temporal.

Endpoints:
  WS  /ws/chat           — start agent workflow, stream progress
  GET /health             — health check
  GET /artifacts/{run_id}/{filename} — download produced files
"""

import json
import os
import re
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from temporalio.client import Client
from temporalio.contrib.workflow_streams import WorkflowStreamClient

from temporal.workflows import AgentWorkflow, WorkflowInput
from temporal.activities import AgentProgress

app = FastAPI(title="DeepAgent POC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TASK_QUEUE = "deep-agent-queue"
ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")

# In-memory map of run_id -> workflow_id for reconnection.
# v2: replace with Postgres for multi-instance support.
run_registry: dict[str, str] = {}

_temporal_client: Client | None = None


def _make_run_id(user_message: str) -> str:
    """Generate a human-readable run ID from the user's prompt.

    Example: "Make a PPT on Amazon market sales"
           → "make-a-ppt-on-amazon_2026-07-24_14-30-05"
    """
    # Take first 6 words, lowercase, keep only alphanumeric + spaces
    words = re.sub(r"[^a-zA-Z0-9 ]", "", user_message).lower().split()[:6]
    slug = "-".join(words) if words else "run"
    # Truncate slug to 40 chars max
    slug = slug[:40].rstrip("-")
    # Append timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{slug}_{timestamp}"


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        _temporal_client = await Client.connect(addr)
    return _temporal_client
```

**Setup section:**

- **Lines 10–13:** Imports — JSON handling, OS, regex for slug generation, datetime for timestamps.
- **Lines 15–19:** FastAPI and Temporal SDK imports.
- **Line 24 (`app = FastAPI(...)`):** Creates the FastAPI application instance.
- **Lines 26–31 (CORS middleware):** Allows the React frontend (running on port 3000) to connect to this server (running on port 8000). `allow_origins=["*"]` permits all origins (fine for development).
- **Line 33 (`TASK_QUEUE`):** The Temporal task queue name — must match the worker.
- **Line 34 (`ARTIFACT_BASE`):** Base directory for storing generated files.
- **Line 38 (`run_registry`):** In-memory dictionary mapping `run_id → workflow_id`. This lets users reconnect to in-progress runs. (v2: would be replaced with a database.)
- **Lines 43–56 (`_make_run_id`):** Generates human-readable folder names from the user's prompt. For example, "Make a PPT on Amazon market sales" becomes `make-a-ppt-on-amazon_2026-07-24_14-30-05`. This replaces the old random hex IDs like `4cb43945`.
- **Lines 59–64 (`get_temporal_client`):** Singleton pattern — creates a Temporal client connection once and reuses it.

```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Health endpoint:** Simple health check for monitoring / load balancers.

```python
@app.get("/artifacts/{run_id}/{filename}")
async def download_artifact(run_id: str, filename: str):
    path = os.path.join(ARTIFACT_BASE, run_id, filename)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, filename=filename)
```

**Artifact download endpoint:** Serves generated files (PPTs, spreadsheets, HTML pages) for download. The URL pattern is `/artifacts/{run_id}/{filename}`, e.g., `/artifacts/make-a-ppt-on-amazon_2026-07-24/presentation.pptx`.

```python
@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    try:
        # Wait for the first message: { "message": "...", "run_id": "..." (optional) }
        raw = await websocket.receive_text()
        data = json.loads(raw)
        user_message = data.get("message", "")
        run_id = data.get("run_id")

        client = await get_temporal_client()

        if run_id and run_id in run_registry:
            # Reconnect to an existing workflow
            workflow_id = run_registry[run_id]
            await websocket.send_text(json.dumps({
                "type": "status",
                "run_id": run_id,
                "detail": "Reconnected to in-progress run",
            }))
        else:
            # Start a new workflow
            run_id = run_id or _make_run_id(user_message)
            workflow_id = f"agent-{run_id}"
            run_registry[run_id] = workflow_id

            await client.start_workflow(
                AgentWorkflow.run,
                WorkflowInput(run_id=run_id, user_message=user_message),
                id=workflow_id,
                task_queue=TASK_QUEUE,
            )

            await websocket.send_text(json.dumps({
                "type": "status",
                "run_id": run_id,
                "detail": f"Started agent run: {run_id}",
            }))

        # Subscribe to progress stream
        stream_client = WorkflowStreamClient.create(
            client,
            workflow_id=workflow_id,
            batch_interval=timedelta(milliseconds=200),
        )
        progress_topic = stream_client.topic("progress", type=AgentProgress)

        got_done = False
        try:
            async with stream_client:
                async for item in progress_topic.subscribe():
                    evt: AgentProgress = item.data
                    msg = {
                        "type": "progress",
                        "run_id": run_id,
                        "step": evt.step,
                        "detail": evt.detail,
                        "artifacts": evt.artifacts,
                    }
                    await websocket.send_text(json.dumps(msg))

                    if evt.step == "done":
                        got_done = True
                        break
        except Exception:
            pass  # Stream closed when workflow completed

        # If stream ended without a done event, send one
        if not got_done:
            import os
            artifact_dir = os.path.join(ARTIFACT_BASE, run_id)
            artifacts = (
                os.listdir(artifact_dir) if os.path.isdir(artifact_dir) else []
            )
            await websocket.send_text(json.dumps({
                "type": "progress",
                "run_id": run_id,
                "step": "done",
                "detail": (
                    f"Completed. Files: {', '.join(artifacts)}"
                    if artifacts else "Completed."
                ),
                "artifacts": artifacts,
            }))

    except WebSocketDisconnect:
        pass  # Client disconnected — workflow continues in Temporal
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "detail": str(e),
            }))
        except Exception:
            pass
```

**WebSocket chat endpoint — the main entry point.** This is where all the action happens:

1. **Accepts the WebSocket connection** from the browser.
2. **Receives the first message** — expects `{ "message": "user prompt", "run_id": "optional" }`.
3. **Reconnection logic** — If the client provides a `run_id` that exists in `run_registry`, it reconnects to the in-progress workflow instead of starting a new one.
4. **New workflow** — If no existing run, generates a human-readable `run_id` from the prompt, starts a Temporal workflow, and registers it.
5. **Progress streaming** — Subscribes to the workflow's progress stream and forwards every event to the browser in real-time.
6. **Done handling** — When the agent finishes, sends a final "done" event with the list of generated files.
7. **Error handling** — Client disconnect doesn't kill the workflow (Temporal keeps it running). Errors are sent back to the browser as JSON.

```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
```

**Entry point:** Runs the FastAPI server on port 8000 with hot-reload enabled for development.

---

### 6.4 Frontend Layer — User Interface

The frontend is a single-page React application that provides a chat interface.

---

#### `frontend/index.html` — HTML Shell

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DeepAgent</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

**Purpose:** The minimal HTML page that hosts the React app. The `<div id="root">` is where React mounts the UI. Vite handles compiling the `.tsx` file.

---

#### `frontend/src/main.tsx` — React Entry Point

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.tsx";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

**Purpose:** Standard React 19 bootstrapping — finds the `#root` div and renders the `App` component inside `StrictMode` (which enables additional development warnings).

---

#### `frontend/src/App.tsx` — Chat UI Component

```tsx
import { useState, useRef, useEffect, useCallback } from "react";

interface Message {
  type: "user" | "status" | "progress" | "error";
  text: string;
  artifacts?: string[];
  runId?: string;
}

const WS_URL = `ws://${window.location.hostname}:8000/ws/chat`;
```

**Setup:**

- **Lines 3–8 (`Message` interface):** TypeScript type for chat messages. Each message has a `type` (user input, status update, progress event, or error), `text` content, optional list of `artifacts` (filenames), and optional `runId`.
- **Line 10 (`WS_URL`):** WebSocket URL pointing to the FastAPI backend on port 8000.

```tsx
export default function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
```

**State management:**

- `input` — The text the user is currently typing.
- `messages` — Array of all chat messages (user messages + agent progress events).
- `connected` — Whether a WebSocket connection is active (disables the send button while running).
- `runId` — The current run's ID (used for reconnection).
- `wsRef` — Ref to the WebSocket object.
- `bottomRef` — Ref to a dummy div at the bottom of the chat for auto-scrolling.

```tsx
  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(scrollToBottom, [messages, scrollToBottom]);
```

**Auto-scroll:** Whenever new messages arrive, smoothly scrolls the chat to the bottom.

```tsx
  const connect = useCallback(
    (message: string, existingRunId?: string) => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        ws.send(
          JSON.stringify({
            message,
            run_id: existingRunId || undefined,
          })
        );
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.run_id && !runId) {
          setRunId(data.run_id);
          sessionStorage.setItem("deepagent_run_id", data.run_id);
        }

        const msg: Message = {
          type: data.type || "status",
          text: data.detail || data.message || JSON.stringify(data),
          artifacts: data.artifacts || [],
          runId: data.run_id,
        };
        setMessages((prev) => [...prev, msg]);

        if (data.step === "done") {
          setConnected(false);
          sessionStorage.removeItem("deepagent_run_id");
        }
      };

      ws.onclose = () => setConnected(false);
      ws.onerror = () => setConnected(false);
    },
    [runId]
  );
```

**WebSocket connection handler:**

- **Opens** a new WebSocket to the backend.
- **On open:** Sends the user's message (or a reconnection request with an existing `run_id`).
- **On message:** Parses incoming JSON events from the backend:
  - Saves the `run_id` to `sessionStorage` (persists across page reloads).
  - Appends each event as a new message in the chat.
  - When the agent sends `step: "done"`, marks the connection as closed and clears the stored `run_id`.
- **On close/error:** Marks as disconnected.

```tsx
  // Reconnect to in-progress run on mount
  useEffect(() => {
    const savedRunId = sessionStorage.getItem("deepagent_run_id");
    if (savedRunId) {
      setMessages([{ type: "status", text: "Reconnecting to previous run..." }]);
      connect("", savedRunId);
    }
  }, [connect]);
```

**Auto-reconnection:** On page load, checks if there's a saved `run_id` in `sessionStorage`. If so, reconnects to the in-progress run — this is what makes the "close tab and come back" feature work.

```tsx
  const handleSend = () => {
    const text = input.trim();
    if (!text) return;

    setMessages((prev) => [...prev, { type: "user", text }]);
    setInput("");
    connect(text);
  };
```

**Send handler:** When the user clicks Send or presses Enter:
1. Adds the user's message to the chat.
2. Clears the input field.
3. Opens a WebSocket connection with the message.

```tsx
  return (
    <div style={styles.container}>
      <h1 style={styles.header}>DeepAgent</h1>
      <p style={styles.sub}>General-purpose autonomous agent. Ask anything.</p>

      <div style={styles.chatBox}>
        {messages.map((msg, i) => (
          <div key={i} style={styles.message}>
            <span style={styles.badge(msg.type)}>{msg.type}</span>
            <span style={styles.text}>{msg.text}</span>
            {msg.artifacts && msg.artifacts.length > 0 && msg.runId && (
              <div style={styles.artifacts}>
                {msg.artifacts.map((f) => (
                  <a
                    key={f}
                    href={`/artifacts/${msg.runId}/${f}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={styles.downloadLink}
                  >
                    {f}
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={styles.inputRow}>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="e.g. Make a PPT on Amazon market sales"
          disabled={connected}
        />
        <button style={styles.button} onClick={handleSend} disabled={connected}>
          {connected ? "Running..." : "Send"}
        </button>
      </div>
    </div>
  );
```

**JSX (the UI):**

- **Header** — "DeepAgent" title and subtitle.
- **Chat box** — Scrollable area showing all messages:
  - Each message has a colored **badge** (blue for user, green for progress, purple for status, red for error).
  - If a message has **artifacts**, download buttons appear as blue links.
- **Input row** — Text input (disabled while running) and a Send button (shows "Running..." while active).

```tsx
const styles = {
  container: { maxWidth: 700, margin: "2rem auto", fontFamily: "system-ui, sans-serif", padding: "0 1rem" },
  header: { margin: 0, fontSize: "1.8rem" },
  sub: { color: "#666", marginTop: 4 },
  chatBox: { border: "1px solid #ddd", borderRadius: 8, padding: "1rem", height: 400, overflowY: "auto", marginTop: "1rem", background: "#fafafa" },
  message: { marginBottom: 8, display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8 },
  badge: (type) => ({ /* color-coded badges */ }),
  text: { flex: 1, minWidth: 0 },
  artifacts: { width: "100%", marginTop: 4, paddingLeft: 60 },
  downloadLink: { display: "inline-block", marginRight: 8, padding: "4px 10px", background: "#1976d2", color: "#fff", borderRadius: 4, textDecoration: "none", fontSize: 13 },
  inputRow: { display: "flex", gap: 8, marginTop: "1rem" },
  input: { flex: 1, padding: "10px 14px", fontSize: 15, border: "1px solid #ccc", borderRadius: 6 },
  button: { padding: "10px 24px", fontSize: 15, background: "#1976d2", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" },
};
```

**Inline styles:** All styling is done with JavaScript objects (no CSS files). Uses a clean, modern design with Material Design-inspired blue (#1976d2) as the accent color.

---

### 6.5 Configuration Files

#### `frontend/vite.config.ts` — Vite Build Configuration

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
      "/artifacts": {
        target: "http://localhost:8000",
      },
    },
  },
});
```

**Purpose:** Configures the Vite development server:
- **Port 3000** — The React dev server runs here.
- **Proxy `/ws`** — WebSocket requests are proxied to the FastAPI backend on port 8000 (avoids CORS issues in development).
- **Proxy `/artifacts`** — Artifact download requests are also proxied to the backend.

#### `frontend/tsconfig.json` — TypeScript Configuration

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

**Purpose:** TypeScript compiler settings — targets modern JavaScript (ES2020), enables strict type checking, uses React JSX transform, and only compiles files in `src/`.

#### `.env.example` — Environment Variable Template

```
GOOGLE_API_KEY=your-google-api-key-here
TAVILY_API_KEY=tvly-...
TEMPORAL_ADDRESS=localhost:7233
ARTIFACT_BASE=./artifacts
```

**Purpose:** Template showing required environment variables:
- `GOOGLE_API_KEY` — API key for Google Gemini (the AI model).
- `TAVILY_API_KEY` — API key for Tavily (web search service).
- `TEMPORAL_ADDRESS` — Address of the Temporal server.
- `ARTIFACT_BASE` — Directory where generated files are stored.

---

## 7. End-to-End Request Flow

Here's exactly what happens when a user types *"Make a PPT on Amazon market sales"* and hits Send:

```
STEP 1: USER INPUT
├── User types message in React chat UI
├── React sends WebSocket message: { "message": "Make a PPT on Amazon market sales" }
└── WebSocket connects to ws://localhost:8000/ws/chat

STEP 2: BACKEND RECEIVES
├── FastAPI WebSocket handler accepts connection
├── Parses incoming JSON message
├── Generates run_id: "make-a-ppt-on-amazon-market_2026-07-24_14-30-05"
├── Stores run_id → workflow_id in run_registry
└── Sends status event back: "Started agent run: make-a-ppt-on-amazon-market_2026-07-24_14-30-05"

STEP 3: TEMPORAL WORKFLOW STARTS
├── FastAPI calls client.start_workflow(AgentWorkflow.run, ...)
├── Temporal server schedules the workflow on "deep-agent-queue"
├── Temporal worker picks up the workflow
└── Workflow executes run_deep_agent activity

STEP 4: AGENT ACTIVITY RUNS
├── Creates artifact directory: artifacts/make-a-ppt-on-amazon-market_2026-07-24_14-30-05/
├── Sets ARTIFACT_DIR environment variable
├── Creates Deep Agent (Gemini 3.5 Flash + tools)
├── Publishes progress: "starting" → "planning"
└── Invokes agent.astream() with the user's message

STEP 5: AGENT PLANS & ACTS
├── Agent reads system prompt, understands the task
├── Agent calls write_todos to plan:
│   ├── Step 1: Research Amazon market data
│   ├── Step 2: Organize findings into slides
│   └── Step 3: Generate PowerPoint
├── Progress published: "thinking" events
│
├── Agent calls web_search("Amazon market sales 2026")
│   ├── Tavily API returns 5 search results
│   ├── Agent reads and processes results
│   └── Progress published: "tool_call: web_search"
│
├── Agent calls generate_pptx(title="Amazon Market Sales", slides=[...])
│   ├── python-pptx creates presentation.pptx
│   ├── Saves to artifacts/make-a-ppt-on-amazon-market_2026-07-24_14-30-05/presentation.pptx
│   └── Progress published: "artifact: presentation.pptx"
│
└── Agent returns final response text

STEP 6: COMPLETION
├── Activity lists files in artifact dir: ["presentation.pptx"]
├── Publishes "result" event with artifact list
├── Workflow publishes "done" event
├── FastAPI forwards "done" to browser via WebSocket
└── React UI shows download link for presentation.pptx

STEP 7: USER DOWNLOADS
├── User clicks "presentation.pptx" download link
├── Browser requests GET /artifacts/make-a-ppt-on-amazon-market_2026-07-24_14-30-05/presentation.pptx
├── FastAPI serves the file via FileResponse
└── User opens the PowerPoint file
```

### Reconnection Flow (if user closes browser mid-run)

```
1. User closes browser tab during Step 5
2. Temporal workflow continues running (it's durable!)
3. User reopens the page
4. React checks sessionStorage for saved run_id
5. React sends: { "message": "", "run_id": "make-a-ppt-on-amazon-market_2026-07-24_14-30-05" }
6. FastAPI looks up run_id in run_registry → finds workflow_id
7. FastAPI re-subscribes to WorkflowStream
8. Remaining progress events are forwarded to the browser
9. User sees the completion and download link
```

---

## 8. Setup & Running Instructions

### Prerequisites

- **Python 3.11+**
- **Node.js 20+**
- **Temporal CLI** — install from [docs.temporal.io/cli](https://docs.temporal.io/cli)

### Step 1: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `GOOGLE_API_KEY` — Get from [Google AI Studio](https://aistudio.google.com/)
- `TAVILY_API_KEY` — Get from [tavily.com](https://tavily.com/)

### Step 2: Install Dependencies

```bash
# Python
pip install -e ".[dev]"

# Frontend
cd frontend && npm install && cd ..
```

### Step 3: Start All Services (4 terminals)

**Terminal 1 — Temporal Dev Server:**
```bash
temporal server start-dev
```

**Terminal 2 — Temporal Worker:**
```bash
python -m temporal.worker
```

**Terminal 3 — FastAPI Backend:**
```bash
python -m backend.main
```

**Terminal 4 — React Frontend:**
```bash
cd frontend && npm run dev
```

### Step 4: Use

Open **http://localhost:3000** in your browser and type a request.

---

## 9. Key Design Decisions

### Why Temporal?

Without Temporal, a long-running AI task (which can take several minutes) would be vulnerable to:
- Server crashes killing the task
- Browser disconnects losing the connection
- No retry mechanism if the AI model has a transient error

Temporal provides automatic retries, persistence, and crash recovery. The user can close their browser and come back later — the task keeps running.

### Why Deep Agents?

Deep Agents (LangChain) provides:
- Autonomous tool selection — the AI decides which tools to use
- Built-in planning capabilities (`write_todos`)
- Streaming execution for real-time progress
- Easy tool registration (just write a Python function)

### Why WebSocket instead of REST?

Agent tasks take minutes, not milliseconds. REST polling would be wasteful. WebSocket provides:
- Real-time streaming of progress events
- Low latency — events arrive immediately
- Bidirectional communication for future multi-turn features

### Why human-readable artifact folder names?

Previously: `artifacts/4cb43945/presentation.pptx` — impossible to know what's inside without opening.
Now: `artifacts/make-a-ppt-on-amazon_2026-07-24_14-30-05/presentation.pptx` — immediately clear.

---

## 10. Future Roadmap (v2)

| Feature | Current (v1) | Planned (v2) |
|---------|-------------|--------------|
| **State storage** | In-memory `run_registry` dict | PostgreSQL database |
| **File storage** | Local disk `./artifacts/` | S3-compatible object store |
| **Agent memory** | None (stateless per run) | pgvector for cross-session memory |
| **Deployment** | Local development | Kubernetes with horizontal scaling |
| **Multi-turn** | Single message per run | Full conversation history |
| **Authentication** | None | User accounts + API keys |

---

*Document generated for DeepAgent POC — July 2026*

# How the Bidirectional WebSocket Works in DeepAgent

A plain-English explanation of how data flows between the browser and the AI agent in real time, and how that powers features like live web search results.

---

## The Big Picture (30-Second Version)

When you type a message into DeepAgent, here is what happens:

1. Your browser opens a **WebSocket** to the server (a persistent two-way pipe).
2. The server kicks off an **AI agent** that thinks, searches the web, and builds files.
3. As the agent works, every little update (each word it writes, each URL it reads, each file it creates) gets pushed **back through the pipe** to your browser in real time.
4. Your browser can also push messages **back to the server** through the same pipe (e.g. "cancel this task").

That is what "bidirectional" means: data flows in **both directions** through one connection, at the same time.

---

## Why Not Just Use Normal HTTP?

Normal HTTP works like ordering food at a counter:

```
You:     "Give me search results for AI trends"
Server:  ... waits 30 seconds ...
Server:  "Here's everything, all at once"
```

The problem: the agent might take 60 seconds to finish. You see **nothing** until it is done. No progress, no partial results, no way to cancel.

WebSockets work like a phone call:

```
You:     "Search for AI trends"
Server:  "OK, searching..."            (instant)
Server:  "Found: wikipedia.org/AI"      (1 second later)
Server:  "Found: nature.com/ai-2025"    (2 seconds later)
Server:  "Here's my summary so far..."  (3 seconds later)
You:     "Stop, that's enough"          (you interrupt)
Server:  "Cancelled."
```

Both sides can talk whenever they want. No waiting.

---

## The Four Layers

DeepAgent has four layers stacked on top of each other. Each one talks to the next:

```
+-----------------------+
|   1. BROWSER (React)  |   You see this
+-----------+-----------+
            |
        WebSocket
            |
+-----------+-----------+
|   2. API SERVER       |   FastAPI on port 8000
|      (FastAPI)        |
+-----------+-----------+
            |
      WorkflowStream
            |
+-----------+-----------+
|   3. WORKFLOW ENGINE  |   Temporal (keeps things reliable)
|      (Temporal)       |
+-----------+-----------+
            |
       Activity call
            |
+-----------+-----------+
|   4. AI AGENT         |   Gemini + Tools (web search, etc.)
+-----------------------+
```

### Layer 1: Browser (React)

The frontend lives in `frontend/src/App.tsx`. It does three things:

- **Sends your message** to the server when you hit Send
- **Receives events** from the server and draws them on screen
- **Sends "cancel"** if you hit Stop

### Layer 2: API Server (FastAPI)

The backend lives in `backend/main.py`. It is the middleman:

- Accepts the WebSocket connection from the browser
- Starts a Temporal workflow for each new message
- Subscribes to the workflow's event stream
- **Forwards every event** from the workflow to the browser
- **Listens for control messages** (like cancel) from the browser and relays them to the workflow

It runs **two tasks at the same time** on each connection:

| Task | Direction | What it does |
|------|-----------|--------------|
| `_forward_events` | Server -> Browser | Reads events from Temporal, sends them to the browser |
| `_read_control` | Browser -> Server | Reads messages from the browser, sends cancel to Temporal |

### Layer 3: Workflow Engine (Temporal)

The workflow lives in `temporal/workflows.py`. Temporal is like a supervisor:

- If the agent crashes, Temporal **retries** it automatically (up to 3 times)
- If the server restarts, Temporal **picks up where it left off**
- It uses a **WorkflowStream** as a message queue between the agent and the API server

### Layer 4: AI Agent

The agent is created in `agent/core.py` and its tools live in `agent/tools.py`. This is where the actual thinking happens. The agent:

- Reads your message
- Decides what tools to use
- Calls tools (web search, file generation, etc.)
- Writes a response

---

## What is an "Event"?

Every time something happens inside the agent, it creates an **event** -- a small JSON message. Here are all the event types:

| Event | When it fires | What it contains |
|-------|--------------|------------------|
| `run_start` | Agent begins working | Your original message |
| `llm_token` | Agent writes a word | The text chunk (streamed) |
| `tool_start` | Agent starts using a tool | Tool name, arguments |
| `tool_progress` | Tool has an update | Progress label (e.g. a URL) |
| `tool_end` | Tool finished | Output preview, duration |
| `plan` | Agent writes a to-do list | The plan text |
| `artifact` | A file was created | Filename |
| `done` | Agent is finished | Final response, all files |
| `error` | Something went wrong | Error message |
| `cancelled` | You cancelled the run | Cancellation confirmation |

Every event has:
- `seq` -- a number that goes up by 1 each time (0, 1, 2, 3...). Used to prevent duplicates.
- `step_id` -- an ID that links `tool_start`, `tool_progress`, and `tool_end` together for the same tool call.
- `run_id` -- which run this belongs to.

---

## How Web Search Shows Up Live

This is the feature you care about most. Here is exactly what happens when the agent decides to search the web:

### Step 1: Agent calls `web_search("AI trends 2025")`

In `agent/tools.py`, the `web_search` function runs:

```python
async def web_search(query: str) -> str:
    # Tell the UI we're searching
    await _emit(f"Searching: {query}", "web_search")

    # Call Tavily API
    results = client.search(query, max_results=5)

    # Tell the UI about each URL we found
    for r in results:
        await _emit(f"Read: {title} -- {url}", "web_search")

    return json.dumps(results)
```

### Step 2: `_emit()` calls the progress callback

Before the agent started, the activity set up a **callback function**:

```python
# In activities.py, before running the agent:
async def _on_tool_progress(label, tool_name):
    progress.publish(AgentProgress(
        type="tool_progress",
        label=label,            # e.g. "Read: Wikipedia -- https://en.wikipedia.org/..."
        step_id=active_step_id, # links this to the tool_start event
        tool=tool_name,         # "web_search"
    ))

set_progress_callback(_on_tool_progress)
```

When `web_search` calls `_emit(...)`, it calls this callback, which publishes an event to the WorkflowStream.

### Step 3: Event flows through the pipeline

```
web_search calls _emit("Read: Wikipedia -- https://...")
    |
    v
_on_tool_progress callback publishes AgentProgress to WorkflowStream
    |
    v
FastAPI's _forward_events task receives it from WorkflowStream
    |
    v
FastAPI sends JSON over WebSocket to browser:
    {
      "event_type": "tool_progress",
      "tool": "web_search",
      "label": "Read: Wikipedia -- https://en.wikipedia.org/...",
      "step_id": "01a014b3-34e0-..."
    }
    |
    v
Browser's ws.onmessage fires, calls reduceEvent()
    |
    v
reduceEvent finds the tool block with matching step_id,
appends the label to its progress[] array
    |
    v
React re-renders, you see "en.wikipedia.org" appear as a clickable link
```

### Step 4: The full sequence on screen

What the user sees in real time:

```
[spinner] web_search
  |  Searching: AI trends 2025
  |  Read: Wikipedia -- en.wikipedia.org        <-- clickable
  |  Read: Nature -- nature.com/ai-review       <-- clickable
  |  Read: MIT Tech Review -- technologyreview.com  <-- clickable
web_search · 2.3s                               <-- spinner stops
```

---

## How Cancellation Works (Both Directions)

Cancellation is the clearest example of "bidirectional":

```
1. You click "Stop"
   Browser sends:  { type: "cancel" }
                        |
                        v
2. FastAPI receives it in _read_control()
   Calls:  temporal_client.get_workflow_handle(id).cancel()
   Sends back:  { event_type: "cancel_requested" }  (instant feedback)
                        |
                        v
3. Temporal cancels the activity
   Activity catches asyncio.CancelledError
   Publishes:  { type: "cancelled", label: "Run cancelled by user" }
                        |
                        v
4. FastAPI forwards the "cancelled" event to browser
   Browser sets state to "cancelled", shows "Cancelled" label
   Clears the force-close timer
```

If the server takes too long to respond (>5 seconds), the browser **force-closes** the WebSocket and marks the run as cancelled locally.

---

## How Past Runs Are Saved and Replayed

Every event that flows through the WebSocket is also **saved to disk** as a JSONL file (one JSON object per line):

```
artifacts/.events/research-ai-trends_2025-08-18_14-32-45.jsonl
```

Each line is one event:
```json
{"type":"progress","event_type":"run_start","label":"Research AI trends",...}
{"type":"progress","event_type":"tool_start","tool":"web_search",...}
{"type":"progress","event_type":"tool_progress","label":"Read: Wikipedia -- https://...",...}
{"type":"progress","event_type":"tool_end","tool":"web_search","duration_ms":2300,...}
{"type":"progress","event_type":"llm_token","label":"Here are the latest...",...}
{"type":"progress","event_type":"done","artifacts":["index.html"],...}
```

When you click **Reconnect** on a past run:

1. Browser fetches `GET /runs/{run_id}/events`
2. Server reads the JSONL file, returns all events as a JSON array
3. Browser replays every event through the same `reduceEvent()` function
4. The UI rebuilds exactly as it looked when the run finished

---

## Key Files

| File | What it does |
|------|-------------|
| `frontend/src/App.tsx` | WebSocket connection, event reducer, all UI rendering |
| `backend/main.py` | FastAPI WebSocket handler, event forwarding, event persistence |
| `temporal/workflows.py` | Temporal workflow definition, WorkflowStream setup |
| `temporal/activities.py` | Agent execution, event publishing, progress callback wiring |
| `agent/tools.py` | Tool implementations, `_emit()` progress callback |
| `agent/core.py` | Agent creation, system prompt, tool registration |

---

## Glossary

| Term | Meaning |
|------|---------|
| **WebSocket** | A persistent two-way connection between browser and server. Unlike HTTP, both sides can send messages at any time. |
| **Event** | A small JSON message describing something that happened (a word was written, a URL was found, a file was created). |
| **WorkflowStream** | Temporal's built-in message queue that connects the agent activity to the API server. |
| **Temporal** | A workflow engine that makes the agent execution reliable (retries, persistence, cancellation). |
| **Activity** | Temporal's term for a unit of work. Our activity runs the AI agent. |
| **Reducer** | A function that takes the current UI state + one event and returns the new UI state. Called once per event. |
| **JSONL** | "JSON Lines" -- a file format where each line is a valid JSON object. Used to store event history. |
| **step_id** | A unique ID that links tool_start, tool_progress, and tool_end events for the same tool call. |
| **seq** | A sequence number on each event (0, 1, 2, ...) used to prevent the same event from being processed twice. |
| **Callback** | A function passed from one layer to another. The activity passes a callback to the tools so they can publish events without knowing about Temporal. |

"""
FastAPI server — thin interface between React UI and Temporal.

Endpoints:
  WS  /ws/chat           — start agent workflow, stream progress
  GET /health             — health check
  GET /artifacts/{run_id}/{filename} — download produced files
"""

import asyncio
import contextlib
import json
import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from temporalio.client import Client
from temporalio.contrib.workflow_streams import WorkflowStreamClient
from temporalio.service import RPCError

from temporal.workflows import AgentWorkflow, WorkflowInput
from temporal.activities import AgentProgress

app = FastAPI(title="DeepAgent POC")

# Restrict CORS to the frontend dev origin(s). Override with CORS_ORIGINS
# (comma-separated) for other environments.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASK_QUEUE = "deep-agent-queue"
ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")
REGISTRY_FILE = os.path.join(ARTIFACT_BASE, ".run_registry.json")
EVENTS_DIR = os.path.join(ARTIFACT_BASE, ".events")

# Persistent map of run_id -> {workflow_id, user_message, status}
run_registry: dict[str, dict] = {}

_temporal_client: Client | None = None

TERMINAL_EVENT_TYPES = {"done", "cancelled", "error"}

os.makedirs(EVENTS_DIR, exist_ok=True)


def _save_registry():
    """Persist run_registry to disk atomically.

    Write to a temp file in the same directory, then os.replace() it over the
    target. os.replace is atomic on the same filesystem, so a crash mid-write
    can never leave a truncated registry.
    """
    os.makedirs(ARTIFACT_BASE, exist_ok=True)
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(run_registry, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, REGISTRY_FILE)


def _load_registry():
    """Load run_registry from JSON file + scan artifact dirs for any missing entries."""
    # Load saved registry
    if os.path.isfile(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for run_id, info in saved.items():
                # Handle old format (string) and new format (dict)
                if isinstance(info, str):
                    run_registry[run_id] = {"workflow_id": info, "user_message": "", "status": "unknown"}
                else:
                    run_registry[run_id] = info
        except json.JSONDecodeError as e:
            # Do NOT silently reset the registry. Preserve the corrupt file for
            # inspection and log loudly so the data loss is visible.
            corrupt = REGISTRY_FILE + ".corrupt"
            with contextlib.suppress(OSError):
                os.replace(REGISTRY_FILE, corrupt)
            logger.error(
                "Run registry %s is corrupt (%s); moved to %s. Recovering run "
                "IDs from artifact directories; user_message/status may be lost.",
                REGISTRY_FILE, e, corrupt,
            )
        except OSError as e:
            logger.error("Could not read run registry %s: %s", REGISTRY_FILE, e)

    # Also scan artifact dirs for runs not in registry (backwards compat)
    if os.path.isdir(ARTIFACT_BASE):
        for name in os.listdir(ARTIFACT_BASE):
            if name.startswith("."):
                continue
            if os.path.isdir(os.path.join(ARTIFACT_BASE, name)) and name not in run_registry:
                run_registry[name] = {
                    "workflow_id": f"agent-{name}",
                    "user_message": "",
                    "status": "done",
                }
        _save_registry()


_load_registry()


def _make_run_id(user_message: str) -> str:
    """Generate a human-readable run ID from the user's prompt."""
    words = re.sub(r"[^a-zA-Z0-9 ]", "", user_message).lower().split()[:6]
    slug = "-".join(words) if words else "run"
    slug = slug[:40].rstrip("-")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{slug}_{timestamp}"


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        _temporal_client = await Client.connect(addr)
    return _temporal_client


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Artifact download
# ---------------------------------------------------------------------------

@app.get("/artifacts/{run_id}/{filename}")
async def download_artifact(run_id: str, filename: str):
    # Resolve the requested path and confirm it stays inside ARTIFACT_BASE.
    # Guards against traversal via URL-encoded segments (e.g. run_id="..",
    # filename=".env"), which would otherwise escape to the project root.
    base = os.path.realpath(ARTIFACT_BASE)
    path = os.path.realpath(os.path.join(base, run_id, filename))
    if path != base and not path.startswith(base + os.sep):
        return JSONResponse({"error": "not found"}, status_code=404)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    # Serve HTML/HTM inline so browsers render them instead of downloading
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".html", ".htm"):
        with open(path, "r", encoding="utf-8") as f:
            from fastapi.responses import HTMLResponse
            return HTMLResponse(f.read())
    return FileResponse(path, filename=filename)


# ---------------------------------------------------------------------------
# List runs
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/events")
async def get_run_events(run_id: str):
    """Return all saved events for a run (for chat replay)."""
    return _load_events(run_id)


@app.get("/runs")
async def list_runs():
    """Return all known runs (newest first), sorted by directory mtime."""
    runs = []
    for run_id, info in run_registry.items():
        artifact_dir = os.path.join(ARTIFACT_BASE, run_id)
        if os.path.isdir(artifact_dir):
            artifacts = [f for f in os.listdir(artifact_dir) if not f.startswith("~$") and not f.startswith(".")]
            mtime = os.path.getmtime(artifact_dir)
        else:
            artifacts = []
            mtime = 0
        runs.append({
            "run_id": run_id,
            "workflow_id": info["workflow_id"],
            "artifacts": artifacts,
            "user_message": info.get("user_message", ""),
            "status": info.get("status", "unknown"),
            "mtime": mtime,
        })
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


# ---------------------------------------------------------------------------
# Phase 2 helpers: bidirectional WebSocket coroutines
# ---------------------------------------------------------------------------

def _event_file(run_id: str) -> str:
    """Path to the JSONL event log for a run."""
    return os.path.join(EVENTS_DIR, f"{run_id}.jsonl")


def _save_event(run_id: str, msg: dict):
    """Append a single event to the run's JSONL log."""
    with open(_event_file(run_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(msg) + "\n")


def _load_events(run_id: str) -> list[dict]:
    """Load all saved events for a run."""
    path = _event_file(run_id)
    if not os.path.isfile(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


async def _forward_events(websocket: WebSocket, progress_topic, run_id: str) -> bool:
    """Pump durable stream events to the browser.
    Returns True if a terminal event was delivered."""
    async for item in progress_topic.subscribe():
        evt: AgentProgress = item.data
        msg = {
            "type": "progress",
            "run_id": run_id,
            "seq": evt.seq,
            "ts": evt.ts,
            "event_type": evt.type,
            "label": evt.label,
            "step_id": evt.step_id,
            "tool": evt.tool,
            "args": evt.args,
            "output_preview": evt.output_preview,
            "duration_ms": evt.duration_ms,
            "artifacts": evt.artifacts,
        }
        # Save event to disk for replay
        _save_event(run_id, msg)
        await websocket.send_text(json.dumps(msg))

        if evt.type in TERMINAL_EVENT_TYPES:
            # Persist status to registry
            if run_id in run_registry:
                run_registry[run_id]["status"] = evt.type
                _save_registry()
            return True
    return False


async def _read_control(
    websocket: WebSocket, client: Client, workflow_id: str, run_id: str
) -> None:
    """Read client->server control messages for the lifetime of the run."""
    while True:
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "cancel":
            handle = client.get_workflow_handle(workflow_id)
            try:
                await handle.cancel()
            except RPCError as e:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "run_id": run_id,
                    "detail": f"Cancel failed: {e}",
                }))
                continue

            # Synthetic acknowledgement so the UI reacts immediately
            await websocket.send_text(json.dumps({
                "type": "progress",
                "run_id": run_id,
                "event_type": "cancel_requested",
                "label": "Cancellation requested",
            }))
            # Do NOT return — keep reading so _forward_events can
            # still deliver the terminal cancelled event.


# ---------------------------------------------------------------------------
# WebSocket chat — start or reconnect to an agent workflow
# ---------------------------------------------------------------------------

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    try:
        # Wait for the first message
        raw = await websocket.receive_text()
        data = json.loads(raw)
        # Accept { "type": "start", "message": "..." } or legacy { "message": "..." }
        user_message = data.get("message", "")
        run_id = data.get("run_id")

        client = await get_temporal_client()

        if run_id and run_id in run_registry:
            # Reconnect to an existing workflow
            workflow_id = run_registry[run_id]["workflow_id"]
            await websocket.send_text(json.dumps({
                "type": "status",
                "run_id": run_id,
                "detail": "Reconnected to in-progress run",
            }))
        else:
            # Start a new workflow
            run_id = run_id or _make_run_id(user_message)
            workflow_id = f"agent-{run_id}"
            run_registry[run_id] = {
                "workflow_id": workflow_id,
                "user_message": user_message,
                "status": "running",
            }
            _save_registry()

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
            batch_interval=timedelta(milliseconds=50),
        )
        progress_topic = stream_client.topic("progress", type=AgentProgress)

        got_terminal = False

        async with stream_client:
            forward = asyncio.create_task(
                _forward_events(websocket, progress_topic, run_id)
            )
            control = asyncio.create_task(
                _read_control(websocket, client, workflow_id, run_id)
            )

            done, pending = await asyncio.wait(
                {forward, control}, return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                    raise exc
                if exc is None and task is forward:
                    got_terminal = bool(task.result())

        # If stream ended without a terminal event, synthesise done
        if not got_terminal:
            artifact_dir = os.path.join(ARTIFACT_BASE, run_id)
            artifacts = [
                f for f in os.listdir(artifact_dir)
                if not f.startswith("~$")
            ] if os.path.isdir(artifact_dir) else []
            await websocket.send_text(json.dumps({
                "type": "progress",
                "run_id": run_id,
                "event_type": "done",
                "label": f"Completed. Files: {', '.join(artifacts)}" if artifacts else "Completed.",
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    # Bind to loopback by default so the API isn't exposed to the whole
    # network. Override with HOST (e.g. 0.0.0.0) behind a trusted proxy.
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("backend.main:app", host=host, port=8000, reload=True)

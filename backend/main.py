"""
FastAPI server — thin interface between React UI and Temporal.

Endpoints:
  POST /runs                          — start an agent workflow
  POST /runs/{run_id}/cancel          — cancel a run
  GET  /runs                          — list runs
  GET  /runs/{run_id}/stream          — SSE stream of v1 events
  GET  /health                        — health check
  GET  /artifacts/{run_id}/{filename} — download produced files
"""

import contextlib
import json
import logging
import os
import re
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
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

# Persistent map of run_id -> {workflow_id, user_message, status}
run_registry: dict[str, dict] = {}

_temporal_client: Client | None = None

TERMINAL_EVENT_TYPES = {"done", "cancelled", "error"}


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
# v1 event envelope + REST/SSE transport (frontend rewrite)
# ---------------------------------------------------------------------------

class StartRunBody(BaseModel):
    message: str
    thread_id: str | None = None


def _v1_envelope(offset: int, evt: AgentProgress, run_id: str) -> dict:
    """Map an internal AgentProgress to the versioned, discriminated v1 event.

    Identity fields user_id/org_id are present but null until Mandate 2 —
    reserved now so stored events and emitters never need a later migration.
    """
    base = {
        "v": 1,
        "run_id": run_id,
        "offset": offset,
        "ts": evt.ts,
        "user_id": None,
        "org_id": None,
    }
    t = evt.type
    if t == "run_start":
        base.update(type="run.started", prompt=evt.label)
    elif t == "llm_token":
        base.update(type="text.delta", text=evt.label)
    elif t == "tool_start":
        base.update(type="tool.started", step_id=evt.step_id, name=evt.tool, args=evt.args)
    elif t == "tool_progress":
        base.update(type="tool.progress", step_id=evt.step_id, tool=evt.tool, message=evt.label)
    elif t == "tool_end":
        base.update(type="tool.finished", step_id=evt.step_id, name=evt.tool,
                    status="done", output_preview=evt.output_preview, duration_ms=evt.duration_ms)
    elif t == "plan":
        base.update(type="plan.snapshot", todos=evt.todos or [])
    elif t in ("file", "artifact"):
        fname = evt.artifacts[0] if evt.artifacts else ""
        base.update(type="file.created", filename=fname, url=f"/artifacts/{run_id}/{fname}")
    elif t == "error":
        base.update(type="run.error", message=evt.label)
    elif t == "cancelled":
        base.update(type="run.finished", state="cancelled")
    elif t == "done":
        base.update(type="run.finished", state="done", summary=evt.label, artifacts=evt.artifacts)
    else:
        base.update(type=t, label=evt.label)
    return base


async def _start_agent_run(client: Client, user_message: str, requested_thread: str | None):
    """Start a new agent workflow. Returns (run_id, workflow_id, thread_id).

    thread_id is server-generated and unguessable; a client may continue a
    conversation only by echoing a previously-issued id (validated), never by
    supplying an arbitrary one.
    """
    run_id = _make_run_id(user_message)
    workflow_id = f"agent-{run_id}"
    known_threads = {
        info.get("thread_id") for info in run_registry.values() if info.get("thread_id")
    }
    thread_id = requested_thread if requested_thread in known_threads else uuid.uuid4().hex
    run_registry[run_id] = {
        "workflow_id": workflow_id,
        "user_message": user_message,
        "status": "running",
        "thread_id": thread_id,
    }
    _save_registry()
    await client.start_workflow(
        AgentWorkflow.run,
        WorkflowInput(run_id=run_id, user_message=user_message, thread_id=thread_id),
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return run_id, workflow_id, thread_id


@app.post("/runs")
async def create_run(body: StartRunBody):
    client = await get_temporal_client()
    run_id, workflow_id, thread_id = await _start_agent_run(
        client, body.message, body.thread_id
    )
    return {"run_id": run_id, "workflow_id": workflow_id, "thread_id": thread_id}


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    if run_id not in run_registry:
        return JSONResponse({"error": "unknown run"}, status_code=404)
    client = await get_temporal_client()
    handle = client.get_workflow_handle(run_registry[run_id]["workflow_id"])
    try:
        await handle.cancel()
    except RPCError as e:
        return JSONResponse({"error": f"cancel failed: {e}"}, status_code=500)
    return {"status": "cancel_requested", "run_id": run_id}


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    """SSE stream of v1 events. id: = offset; Last-Event-ID resumes at offset+1,
    so a refresh mid-run replays nothing already seen."""
    if run_id not in run_registry:
        return JSONResponse({"error": "unknown run"}, status_code=404)
    client = await get_temporal_client()
    workflow_id = run_registry[run_id]["workflow_id"]
    last_id = request.headers.get("last-event-id")
    from_offset = (int(last_id) + 1) if last_id and last_id.lstrip("-").isdigit() else 0

    async def event_gen():
        stream_client = WorkflowStreamClient.create(client, workflow_id=workflow_id)
        progress_topic = stream_client.topic("progress", type=AgentProgress)
        async with stream_client:
            async for item in progress_topic.subscribe(from_offset=from_offset):
                evt: AgentProgress = item.data
                env = _v1_envelope(item.offset, evt, run_id)
                if evt.type in TERMINAL_EVENT_TYPES and run_id in run_registry:
                    run_registry[run_id]["status"] = evt.type
                    _save_registry()
                yield f"id: {item.offset}\ndata: {json.dumps(env)}\n\n"
                if evt.type in TERMINAL_EVENT_TYPES:
                    break

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    # Bind to loopback by default so the API isn't exposed to the whole
    # network. Override with HOST (e.g. 0.0.0.0) behind a trusted proxy.
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("backend.main:app", host=host, port=8000, reload=True)

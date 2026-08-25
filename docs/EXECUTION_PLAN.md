# DeepAgent v2 — Execution Plan

> Boss feedback: terminal-toolkit streaming, code execution, Claude-style boxes, skills system, browser notifications, scaling to 1000s of users, and memory isolation.

---

## Current State (What We Have)

```
React Chat UI ──WebSocket──▶ FastAPI ──Temporal──▶ Deep Agent
  (flat message list)          (thin proxy)          (Gemini 3.5 Flash)
                                                     Tools: web_search, pptx, xlsx, html
                                                     Built-ins: filesystem, execute, todos
```

- Streaming works via Temporal WorkflowStream → WebSocket → React
- Single-user, in-memory run registry, local artifact storage
- No persistent memory, no user auth, no skills framework

---

## Target State (What We Need)

```
Terminal-Style React UI ──WebSocket──▶ FastAPI (multi-instance) ──▶ Temporal Cluster
  ├─ xterm.js terminal pane                ├─ Redis pub/sub                ├─ N workers
  ├─ Claude-style bordered boxes           ├─ PostgreSQL (runs, users)     ├─ per-user memory
  ├─ Code blocks with syntax highlight     ├─ S3 artifacts                 ├─ skill router
  ├─ Skill slash commands                  ├─ JWT auth                     └─ sandboxed exec
  └─ Browser notifications                └─ WebSocket fan-out
```

---

## Phase 1: Terminal Toolkit UI + Claude-Style Boxes

**Goal**: Replace the flat message list with a terminal-like interface that renders agent output in structured, Claude-style boxes.

### 1A. Install Terminal UI Dependencies

```bash
cd frontend
npm install xterm @xterm/xterm @xterm/addon-fit react-syntax-highlighter
npm install -D @types/react-syntax-highlighter
```

**Why xterm.js**: It's the same terminal emulator used by VS Code's integrated terminal. It gives us real terminal rendering (ANSI colors, cursor control) for code execution output. The React chat wraps around it — agent "thinking" and tool calls render as styled boxes, while raw code output streams into the xterm pane.

### 1B. Restructure Frontend Message Types

Current message type is flat (`user | status | progress | error`). Extend to support structured blocks:

```typescript
// frontend/src/types.ts (NEW FILE)

interface StreamBlock {
  id: string;
  type: "thinking" | "tool_call" | "tool_result" | "code_exec" | "artifact" | "text" | "error" | "follow_up";
  title?: string;          // e.g. "Searching the web..." or "Running Python"
  content: string;
  status: "streaming" | "complete" | "error";
  collapsible: boolean;    // thinking blocks start collapsed
  artifacts?: string[];
  language?: string;       // for code blocks: "python", "bash", etc.
  metadata?: Record<string, unknown>;
}

interface AgentResponse {
  run_id: string;
  blocks: StreamBlock[];   // ordered list of blocks in this response
}
```

### 1C. Build the Claude-Style Block Renderer

Create a `<StreamBlockRenderer>` component that renders each block type:

```
┌─ Thinking ─────────────────────────────────────┐
│ I need to search for Amazon's latest market     │
│ data and then create a PowerPoint with the...   │
└─────────────────────────────────────────────────┘

┌─ Tool: web_search ──────────────────────────────┐
│ Query: "Amazon market sales 2026 Q2"            │
│ ✓ 5 results found                               │
└─────────────────────────────────────────────────┘

┌─ Code Execution ────────────────────────────────┐
│ ```python                                       │
│ import pandas as pd                             │
│ df = pd.read_csv("data.csv")                    │
│ print(df.describe())                            │
│ ```                                             │
│ ┌─ Output ────────────────────────────────────┐ │
│ │ count    100.0                              │ │
│ │ mean    2847.3                              │ │
│ │ ...                                        │ │
│ └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘

┌─ Follow Up ─────────────────────────────────────┐
│ Would you like me to:                           │
│  • Add more slides with quarterly breakdown?    │
│  • Export the data to Excel as well?            │
│  • Include competitor comparisons?              │
└─────────────────────────────────────────────────┘
```

**Implementation**: Single new file `frontend/src/components/StreamBlock.tsx` (~150 lines). Uses CSS border + border-radius + colored left-border to match Claude's aesthetic. Thinking blocks default collapsed with a chevron toggle.

### 1D. Backend Streaming Protocol Update

Modify `temporal/activities.py` to emit structured blocks instead of flat progress events:

```python
# Change AgentProgress to support block-based streaming
@dataclass
class AgentProgress:
    step: str
    detail: str
    artifacts: list[str] = field(default_factory=list)
    block_type: str = "text"           # NEW: thinking, tool_call, code_exec, etc.
    block_id: str = ""                 # NEW: unique ID for updating in-progress blocks
    block_status: str = "complete"     # NEW: streaming | complete | error
    language: str = ""                 # NEW: for code blocks
    follow_ups: list[str] = field(default_factory=list)  # NEW: suggested next actions
```

**Backward compatible**: existing `step` and `detail` fields still work. Frontend checks for `block_type` — if present, renders as a block; otherwise falls back to current flat rendering.

### 1E. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `frontend/src/types.ts` | NEW — shared TypeScript types | Small |
| `frontend/src/components/StreamBlock.tsx` | NEW — block renderer component | Medium |
| `frontend/src/App.tsx` | Replace message list with block-based rendering | Medium |
| `temporal/activities.py` | Emit block_type, block_id, block_status fields | Small |
| `backend/main.py` | Pass through new fields (no logic change) | Trivial |

**Estimated effort**: 1-2 days

---

## Phase 2: Code Execution Streaming

**Goal**: When the agent runs code via the built-in `execute` tool, stream stdout/stderr to the frontend in real-time (not just the final result).

### 2A. How It Works Today

The Deep Agents `execute` built-in runs code and returns the full output as a tool result. We see it only after execution completes.

### 2B. Streaming Code Output

Two approaches (pick one):

**Option A — Poll-based (simpler, works with current Temporal setup)**:
- In `activities.py`, when a `tool_call` event has `name == "execute"`, publish a `code_exec` block with `status: "streaming"`
- After the tool result comes back, publish the same block_id with `status: "complete"` and the output
- Frontend animates a "running..." indicator until complete

**Option B — PTY streaming (real terminal output)**:
- Wrap code execution in a pseudo-terminal (pty) using `pexpect` or `asyncio.subprocess`
- Read stdout line-by-line, publish each line as a partial update on the same block_id
- Frontend uses xterm.js to render raw terminal output character-by-character
- Requires custom execute tool (replaces built-in)

**Recommendation**: Start with **Option A**. It requires zero new dependencies and works within the existing Temporal streaming model. Upgrade to Option B later if real-time line-by-line streaming is a hard requirement.

### 2C. Sandboxed Execution (Required for Multi-User)

When scaling to 1000s of users, code execution MUST be sandboxed:

```
Option 1: Docker containers (simplest)
  - Each code execution spins up a throwaway container
  - Mount only the run's artifact dir
  - CPU/memory limits via Docker
  - 30-second timeout
  - Use: docker run --rm --network none --memory 256m --cpus 0.5

Option 2: gVisor / Firecracker (production-grade)
  - Google's gVisor (runsc) or AWS Firecracker microVMs
  - Sub-second cold start
  - Strong isolation guarantees
  - Use at 1000+ concurrent users

Option 3: Pyodide / WebAssembly (client-side, for simple scripts)
  - Run Python in the browser via WASM
  - Zero backend cost
  - Limited library support
  - Good for simple data analysis only
```

**Recommendation**: Docker containers for Phase 2. Move to Firecracker/gVisor in Phase 4 (scaling).

### 2D. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `temporal/activities.py` | Detect execute tool calls, emit streaming blocks | Medium |
| `agent/tools.py` | Add `run_code` tool with Docker sandboxing | Medium |
| `agent/core.py` | Register `run_code` tool | Trivial |

**Estimated effort**: 1-2 days

---

## Phase 3: Skills System

**Goal**: Pluggable skill modules that the agent can invoke — similar to Claude Code's slash commands.

### 3A. What Is a Skill?

A skill is a self-contained capability with:
- A name and description (for the agent to decide when to use it)
- Input/output schema
- One or more tool functions
- Optional system prompt extension

```
skills/
├── __init__.py          # Skill registry + discovery
├── base.py              # BaseSkill abstract class
├── data_analysis.py     # Skill: analyze CSV/JSON data
├── code_review.py       # Skill: review code for bugs/quality
├── web_scraper.py       # Skill: deep scrape + summarize websites
├── presentation.py      # Skill: enhanced PPT (move from tools.py)
└── report_writer.py     # Skill: generate structured reports
```

### 3B. Skill Base Class

```python
# skills/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SkillManifest:
    name: str                    # e.g. "data_analysis"
    display_name: str            # e.g. "Data Analysis"
    description: str             # For the LLM to understand when to use it
    version: str
    tools: list[callable]        # Tool functions this skill provides
    system_prompt_extension: str  # Appended to agent's system prompt

class BaseSkill(ABC):
    @abstractmethod
    def manifest(self) -> SkillManifest:
        ...

    @abstractmethod
    def get_tools(self) -> list[callable]:
        ...
```

### 3C. Skill Registry

```python
# skills/__init__.py
import importlib, pkgutil

_registry: dict[str, BaseSkill] = {}

def discover_skills():
    """Auto-discover all skill modules in the skills/ directory."""
    for _, name, _ in pkgutil.iter_modules(["skills"]):
        mod = importlib.import_module(f"skills.{name}")
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if isinstance(cls, type) and issubclass(cls, BaseSkill) and cls is not BaseSkill:
                skill = cls()
                _registry[skill.manifest().name] = skill

def get_all_tools() -> list[callable]:
    """Collect all tool functions from all registered skills."""
    tools = []
    for skill in _registry.values():
        tools.extend(skill.get_tools())
    return tools

def get_system_prompt_extensions() -> str:
    """Collect system prompt additions from all skills."""
    parts = []
    for skill in _registry.values():
        ext = skill.manifest().system_prompt_extension
        if ext:
            parts.append(f"## Skill: {skill.manifest().display_name}\n{ext}")
    return "\n\n".join(parts)
```

### 3D. Integrate with Agent Core

```python
# agent/core.py — updated
from skills import discover_skills, get_all_tools, get_system_prompt_extensions

def create_agent():
    discover_skills()
    all_tools = get_all_tools()
    skill_prompts = get_system_prompt_extensions()

    return create_deep_agent(
        model="google_genai:gemini-3.5-flash",
        system_prompt=SYSTEM_PROMPT + "\n\n" + skill_prompts,
        tools=all_tools,
    )
```

### 3E. Migrate Existing Tools to Skills

Move `generate_pptx`, `generate_xlsx`, `generate_html`, `web_search` into skill modules. Keep `agent/tools.py` as a thin re-export for backward compatibility (or delete it).

### 3F. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `skills/__init__.py` | NEW — registry + discovery | Small |
| `skills/base.py` | NEW — BaseSkill ABC | Small |
| `skills/presentation.py` | NEW — migrated from tools.py | Small |
| `skills/spreadsheet.py` | NEW — migrated from tools.py | Small |
| `skills/web_research.py` | NEW — migrated from tools.py | Small |
| `agent/core.py` | Use skill registry instead of manual tool list | Small |

**Estimated effort**: 1 day

---

## Phase 4: Browser Notifications

**Goal**: When a long-running agent task completes, send a browser push notification so the user doesn't have to keep the tab open/focused.

### 4A. Implementation (Frontend Only — No Backend Changes)

```typescript
// frontend/src/utils/notifications.ts (NEW FILE)

export async function requestNotificationPermission(): Promise<boolean> {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  const result = await Notification.requestPermission();
  return result === "granted";
}

export function notifyTaskComplete(runId: string, detail: string) {
  if (Notification.permission !== "granted") return;

  const notification = new Notification("DeepAgent — Task Complete", {
    body: detail || `Run ${runId} has finished.`,
    icon: "/favicon.ico",              // add a favicon
    tag: runId,                         // deduplicate per run
    requireInteraction: false,
  });

  // Click notification → focus the tab
  notification.onclick = () => {
    window.focus();
    notification.close();
  };

  // Auto-close after 10 seconds
  setTimeout(() => notification.close(), 10000);
}
```

### 4B. Hook Into WebSocket Handler

In `App.tsx`, when `data.step === "done"`:

```typescript
if (data.step === "done") {
  notifyTaskComplete(data.run_id, data.detail);
  // ... existing done handling
}
```

Request permission on first user interaction (e.g., when they click "Send" for the first time).

### 4C. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `frontend/src/utils/notifications.ts` | NEW — Notification API wrapper | Small |
| `frontend/src/App.tsx` | Call notifyTaskComplete on done, requestPermission on first send | Trivial |

**Estimated effort**: 1-2 hours

---

## Phase 5: Scaling to 1000s of Users

### 5A. Current Bottlenecks

| Component | Current | Bottleneck At | Fix |
|-----------|---------|---------------|-----|
| FastAPI | Single process, in-memory registry | ~50 concurrent WebSockets | Horizontal scaling + Redis |
| Temporal Worker | Single worker, 1 activity slot | ~5 concurrent agents | Worker pool + multiple instances |
| Artifact Storage | Local disk `./artifacts/` | Single machine disk | S3/MinIO |
| Run Registry | In-memory dict | Lost on restart, not shared | PostgreSQL |
| WebSocket | Per-connection in FastAPI | Memory per connection | Redis pub/sub fan-out |
| Code Execution | Shared process env | Security + resource contention | Docker/Firecracker isolation |

### 5B. Architecture for 1000 Users

```
                         ┌─────────────────────────────┐
                         │       Load Balancer          │
                         │  (nginx / AWS ALB)           │
                         │  sticky sessions for WS      │
                         └──────────┬──────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼───────┐    ┌───────▼───────┐    ┌───────▼───────┐
      │  FastAPI #1    │    │  FastAPI #2    │    │  FastAPI #3    │
      │  (uvicorn)     │    │  (uvicorn)     │    │  (uvicorn)     │
      └───────┬───────┘    └───────┬───────┘    └───────┬───────┘
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
            ┌───────▼──┐    ┌──────▼───┐    ┌──────▼───┐
            │ Redis    │    │ Postgres │    │ S3/MinIO │
            │ pub/sub  │    │ runs +   │    │ artifacts│
            │ + cache  │    │ users +  │    │          │
            │          │    │ memory   │    │          │
            └──────────┘    └──────────┘    └──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   Temporal Cluster   │
                         │   (3+ history nodes) │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼───────┐    ┌───────▼───────┐    ┌───────▼───────┐
      │  Worker #1     │    │  Worker #2     │    │  Worker #N     │
      │  (agent exec)  │    │  (agent exec)  │    │  (agent exec)  │
      └───────────────┘    └───────────────┘    └───────────────┘
```

### 5C. Step-by-Step Scaling Plan

**Step 1: PostgreSQL for State (replaces in-memory dict)**

```python
# backend/db.py (NEW FILE)
import asyncpg

pool: asyncpg.Pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            user_id TEXT,              -- NULL for anonymous
            status TEXT DEFAULT 'running',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id SERIAL PRIMARY KEY,
            run_id TEXT REFERENCES runs(run_id),
            filename TEXT NOT NULL,
            s3_key TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
```

Replace `run_registry` dict in `backend/main.py` with `SELECT/INSERT` on the `runs` table.

**Step 2: S3 for Artifacts (replaces local ./artifacts/)**

```python
# backend/storage.py (NEW FILE)
import boto3

s3 = boto3.client("s3",
    endpoint_url=os.environ.get("S3_ENDPOINT"),  # MinIO for local dev
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)
BUCKET = os.environ.get("S3_BUCKET", "deepagent-artifacts")

async def upload_artifact(run_id: str, filename: str, data: bytes):
    key = f"{run_id}/{filename}"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data)
    return key

async def get_artifact_url(run_id: str, filename: str) -> str:
    key = f"{run_id}/{filename}"
    return s3.generate_presigned_url("get_object",
        Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=3600)
```

**Step 3: Redis Pub/Sub for WebSocket Fan-Out**

Problem: When you have 3 FastAPI instances, the WebSocket client might be connected to FastAPI #1, but the Temporal workflow stream callback might land on FastAPI #2. Redis pub/sub solves this.

```python
# backend/pubsub.py (NEW FILE)
import redis.asyncio as redis

r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

async def publish_progress(run_id: str, event: dict):
    await r.publish(f"run:{run_id}", json.dumps(event))

async def subscribe_progress(run_id: str):
    pubsub = r.pubsub()
    await pubsub.subscribe(f"run:{run_id}")
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield json.loads(message["data"])
```

**Step 4: Multiple Temporal Workers**

```bash
# Launch N workers (each picks up tasks from the same queue)
for i in $(seq 1 $NUM_WORKERS); do
  python -m temporal.worker &
done
```

Each worker can handle multiple concurrent activities. Configure via:

```python
Worker(
    client,
    task_queue=TASK_QUEUE,
    workflows=[AgentWorkflow],
    activities=[run_deep_agent],
    max_concurrent_activities=5,       # 5 agents per worker
    max_concurrent_workflow_tasks=10,
)
```

**Step 5: Load Balancer + Sticky Sessions**

```nginx
# nginx.conf
upstream fastapi {
    ip_hash;  # sticky sessions for WebSocket
    server fastapi-1:8000;
    server fastapi-2:8000;
    server fastapi-3:8000;
}

server {
    location /ws/ {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location / {
        proxy_pass http://fastapi;
    }
}
```

### 5D. Scaling Numbers

| Setup | Concurrent Users | Monthly Cost (AWS est.) |
|-------|-----------------|------------------------|
| Current (single machine) | ~10-20 | $0 (local) |
| 1 FastAPI + 3 Workers + RDS + Redis | ~200-300 | ~$150-250 |
| 3 FastAPI + 10 Workers + RDS + ElastiCache | ~1,000-2,000 | ~$500-800 |
| K8s auto-scaling + Temporal Cloud | ~10,000+ | ~$2,000+ |

### 5E. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `backend/db.py` | NEW — asyncpg connection pool + run queries | Medium |
| `backend/storage.py` | NEW — S3 upload/download | Medium |
| `backend/pubsub.py` | NEW — Redis pub/sub wrapper | Medium |
| `backend/main.py` | Replace in-memory registry with db + Redis | Medium |
| `temporal/activities.py` | Upload artifacts to S3 after creation | Small |
| `temporal/worker.py` | Add max_concurrent config | Trivial |
| `docker-compose.yml` | NEW — Postgres, Redis, MinIO, multi-worker | Medium |
| `nginx.conf` | NEW — load balancer config | Small |

**Estimated effort**: 3-5 days

---

## Phase 6: Memory Isolation (Per-User Context)

### 6A. The Problem

Currently there is zero memory between runs. The agent starts fresh every time. For a multi-user system, we need:

1. **Per-user memory** — each user's agent remembers their past interactions
2. **Cross-run context** — "remember I prefer bullet points" persists across sessions
3. **Isolation** — User A's memory is NEVER visible to User B

### 6B. Architecture: pgvector + Namespaced Collections

```
┌──────────────────────────────────────────────────────────────┐
│                    PostgreSQL + pgvector                      │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Table: user_memory                                      │ │
│  │                                                         │ │
│  │  id | user_id | run_id | content    | embedding | meta  │ │
│  │  ───┼─────────┼────────┼────────────┼───────────┼────── │ │
│  │  1  │ user_A  │ run_1  │ "prefers   │ [0.12,..] │ {...} │ │
│  │     │         │        │  bullets"  │           │       │ │
│  │  2  │ user_A  │ run_2  │ "works on  │ [0.34,..] │ {...} │ │
│  │     │         │        │  ML proj"  │           │       │ │
│  │  3  │ user_B  │ run_3  │ "CEO of    │ [0.56,..] │ {...} │ │
│  │     │         │        │  startup"  │           │       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  Every query is: WHERE user_id = $1   ← ISOLATION ENFORCED  │
│  Similarity: ORDER BY embedding <=> $2 LIMIT 10             │
└──────────────────────────────────────────────────────────────┘
```

### 6C. Memory Service Implementation

```python
# memory/service.py (NEW FILE)

class MemoryService:
    """Per-user isolated memory backed by pgvector."""

    def __init__(self, pool: asyncpg.Pool, embedder):
        self.pool = pool
        self.embedder = embedder  # e.g. sentence-transformers or OpenAI embeddings

    async def store(self, user_id: str, run_id: str, content: str, meta: dict = None):
        """Store a memory entry. Always scoped to user_id."""
        embedding = await self.embedder.embed(content)
        await self.pool.execute("""
            INSERT INTO user_memory (user_id, run_id, content, embedding, meta)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, run_id, content, embedding, json.dumps(meta or {}))

    async def recall(self, user_id: str, query: str, limit: int = 10) -> list[dict]:
        """Retrieve relevant memories. ONLY returns this user's memories."""
        query_embedding = await self.embedder.embed(query)
        rows = await self.pool.fetch("""
            SELECT content, meta, 1 - (embedding <=> $1) AS similarity
            FROM user_memory
            WHERE user_id = $2
            ORDER BY embedding <=> $1
            LIMIT $3
        """, query_embedding, user_id, limit)
        return [dict(r) for r in rows]

    async def forget(self, user_id: str, memory_id: int = None):
        """Delete memories. If memory_id given, delete one; else delete all for user."""
        if memory_id:
            await self.pool.execute(
                "DELETE FROM user_memory WHERE id = $1 AND user_id = $2",
                memory_id, user_id
            )
        else:
            await self.pool.execute(
                "DELETE FROM user_memory WHERE user_id = $1", user_id
            )
```

### 6D. How Isolation Works

**Layer 1 — Database Row-Level Security (RLS)**:
```sql
ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_memory_isolation ON user_memory
    USING (user_id = current_setting('app.current_user_id'));
```
Even if application code has a bug, PostgreSQL itself enforces that User A can never see User B's rows.

**Layer 2 — Application-Level Filtering**:
Every query in `MemoryService` includes `WHERE user_id = $1`. Defense in depth.

**Layer 3 — API-Level Auth**:
JWT token identifies the user. FastAPI middleware extracts `user_id` from the token and passes it to the memory service. No user_id spoofing possible.

```python
# backend/auth.py (NEW FILE)
from fastapi import Depends, HTTPException
from jose import jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401)
    return user_id
```

### 6E. Injecting Memory Into Agent Context

Before each agent run, recall relevant memories and prepend them to the system prompt:

```python
# In temporal/activities.py, before creating the agent:

memories = await memory_service.recall(user_id, user_message, limit=10)
if memories:
    memory_context = "\n".join([f"- {m['content']}" for m in memories])
    extended_prompt = f"{SYSTEM_PROMPT}\n\n## Your Memory of This User\n{memory_context}"
else:
    extended_prompt = SYSTEM_PROMPT
```

After the agent completes, extract key facts and store them:

```python
# After agent completes:
# Use the LLM itself to extract memorable facts
extract_prompt = f"Extract 1-3 key facts worth remembering about this user from this conversation:\n{final_response}"
facts = await llm.extract(extract_prompt)
for fact in facts:
    await memory_service.store(user_id, run_id, fact)
```

### 6F. Alternative: File-Based Memory (Quick Prototype)

If you want memory isolation without PostgreSQL/pgvector for now:

```
memory/
├── users/
│   ├── user_abc123/
│   │   ├── facts.json          # Key-value facts about the user
│   │   ├── preferences.json    # Formatting, style, tool preferences
│   │   └── history/
│   │       ├── run_001.json    # Summary of each past run
│   │       └── run_002.json
│   └── user_def456/
│       └── ...
```

Isolation is enforced by directory path: `memory/users/{user_id}/`. Simple, no database needed, but doesn't scale beyond ~100 users (filesystem overhead).

### 6G. Files to Change

| File | Change | Effort |
|------|--------|--------|
| `memory/__init__.py` | NEW — memory package | Trivial |
| `memory/service.py` | NEW — MemoryService with pgvector | Medium |
| `backend/auth.py` | NEW — JWT auth middleware | Medium |
| `backend/main.py` | Add auth middleware, pass user_id to workflow | Medium |
| `temporal/activities.py` | Recall memories before agent, store after | Medium |
| `temporal/workflows.py` | Accept user_id in WorkflowInput | Small |
| Migration SQL | NEW — user_memory table with pgvector | Small |

**Estimated effort**: 2-3 days

---

## Execution Order (Priority Sequence)

```
Week 1:
  ├── Phase 4: Browser Notifications          [2 hours]  ← Quick win, ship immediately
  ├── Phase 1: Terminal UI + Claude-Style Boxes [2 days]  ← Biggest visual impact
  └── Phase 3: Skills System                   [1 day]   ← Structural improvement

Week 2:
  ├── Phase 2: Code Execution Streaming        [2 days]  ← Core feature
  └── Phase 6: Memory Isolation (file-based)   [1 day]   ← Quick prototype

Week 3-4:
  └── Phase 5: Scaling Infrastructure          [5 days]  ← PostgreSQL, Redis, S3
      └── Phase 6: Memory (upgrade to pgvector) [2 days] ← Production memory
```

---

## Quick Wins (Can Ship Today)

These require minimal code changes and deliver immediate value:

### 1. Browser Notifications — 30 minutes
Add `frontend/src/utils/notifications.ts` (20 lines) + 2 lines in App.tsx.

### 2. Follow-Up Suggestions — 1 hour
Have the agent append follow-up suggestions. Add a `follow_ups` field to `AgentProgress`. Render as a clickable box in the frontend.

### 3. Thinking Block Collapse — 1 hour
Wrap agent "thinking" messages in a `<details>` element so they're collapsed by default (like Claude's thinking blocks).

---

## Tech Stack Additions Summary

| Component | Package | Purpose |
|-----------|---------|---------|
| Terminal UI | `xterm` + `@xterm/addon-fit` | Terminal rendering for code output |
| Syntax Highlighting | `react-syntax-highlighter` | Code blocks in agent responses |
| Database | `asyncpg` + `pgvector` | Persistent runs, user memory |
| Cache/PubSub | `redis[asyncio]` | WebSocket fan-out, session cache |
| Object Storage | `boto3` | S3-compatible artifact storage |
| Auth | `python-jose[cryptography]` | JWT token validation |
| Sandboxing | `docker` SDK | Isolated code execution |
| Embeddings | `sentence-transformers` | Memory vector embeddings |

---

## Key Design Decisions to Confirm

Before executing, confirm these with the team:

1. **Auth provider**: Roll our own JWT vs. use a service (Auth0, Clerk, Supabase Auth)?
2. **Embedding model**: Local sentence-transformers (free, ~100ms) vs. API-based (OpenAI, Gemini)?
3. **Infrastructure**: Self-hosted (Docker Compose) vs. cloud-managed (AWS ECS/EKS, Temporal Cloud)?
4. **Code execution sandbox**: Docker containers vs. cloud sandboxes (AWS Lambda, Modal)?
5. **Frontend framework**: Keep pure React or adopt a component library (shadcn/ui, Radix)?

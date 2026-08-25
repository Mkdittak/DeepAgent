# DeepAgent POC — Architecture

## Three Layers

```
┌─────────────────────────────────────────────────────────┐
│  React Chat UI (frontend/)                              │
│  - Sends user message over WebSocket                    │
│  - Streams live agent steps                             │
│  - Download links for produced artifacts                │
│  - Reconnects to in-progress runs (survives browser close)│
│  - "Past Runs" panel to browse & reconnect to any run   │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket (ws://localhost:8000/ws/chat)
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI (backend/)                                     │
│  - WS /ws/chat: starts Temporal workflow, streams back  │
│  - GET /health                                          │
│  - GET /runs: list all known runs + their artifacts     │
│  - GET /artifacts/{run_id}/{filename}: download files   │
│  - Thin — no reasoning logic                            │
└──────────────────────┬──────────────────────────────────┘
                       │ Temporal Client → start workflow
┌──────────────────────▼──────────────────────────────────┐
│  Temporal (temporal/)                                    │
│  - AgentWorkflow: one workflow per chat request          │
│  - run_deep_agent activity: invokes the Deep Agent      │
│  - WorkflowStream publishes progress events             │
│  - Retries, durability, survives browser close           │
└──────────────────────┬──────────────────────────────────┘
                       │ Activity calls agent
┌──────────────────────▼──────────────────────────────────┐
│  Deep Agent (agent/)                                    │
│  - create_deep_agent() with broad system prompt         │
│  - Tools: web_search, python_exec, pptx, xlsx, html    │
│  - Built-ins: write_todos, filesystem, execute, task    │
│  - Model: anthropic:claude-sonnet-4-6                   │
└─────────────────────────────────────────────────────────┘
```

## Session-Independent Run Flow

```
1. User sends "make a PPT on Amazon market sales" via React
2. FastAPI receives over WebSocket
3. FastAPI starts Temporal workflow (AgentWorkflow) with run_id
4. Temporal activity invokes Deep Agent
5. Agent plans → picks pptx tool → generates presentation.pptx
6. Activity publishes progress events via WorkflowStream
7. FastAPI subscribes to WorkflowStream, forwards to WebSocket
8. React displays live steps + download link

If user closes browser at step 6:
  - Temporal workflow continues to completion
  - On reopen, localStorage run_id auto-reconnects via WebSocket
  - Or: click "Past Runs" → "Reconnect" to pick any prior run
  - FastAPI re-subscribes to WorkflowStream
  - React catches up on all missed events
```

## Future Upgrades (v2 notes)

- **Postgres**: Replace in-memory run store with `asyncpg` for multi-instance state
- **S3**: Replace local disk artifact storage with S3-compatible object store
- **pgvector**: Add vector memory for agent context across sessions
- **K8s**: Containerize workers for horizontal scaling

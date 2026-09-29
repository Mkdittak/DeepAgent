"""
Temporal activity: invokes the Deep Agent and publishes streaming progress.

Streaming path: astream_events(version="v2") — confirmed available on
langchain-core>=1.5.1 and deepagents>=0.6.12 CompiledStateGraph.
"""

import asyncio
import os
import re
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from temporalio import activity
from temporalio.contrib.workflow_streams import WorkflowStreamClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AgentInput:
    run_id: str
    user_message: str
    thread_id: str | None = None  # conversation thread for multi-turn memory (M0)
    # Identity as resolved by the API (WorkflowInput). Trusted as-is; the
    # worker has no session to verify and must not try. None = pre-auth run.
    user_id: str | None = None
    org_id: str | None = None
    recursion_limit: int = 30  # agent step budget, set per run by the API


@dataclass
class AgentProgress:
    seq: int  # monotonic within a run, starts at 0
    ts: str  # ISO-8601 UTC
    run_id: str
    type: str  # run_start, plan, llm_token, tool_start, tool_progress, tool_end, artifact, error, cancelled, done
    label: str  # human-readable one-liner for the UI
    step_id: str | None = None  # correlates tool_start with tool_end
    tool: str | None = None
    args: dict | None = None  # redacted; see _redact
    output_preview: str | None = None  # truncated to 500 chars
    duration_ms: int | None = None  # set on tool_end
    artifacts: list[str] = field(default_factory=list)
    todos: list[dict] | None = None  # structured plan.snapshot (write_todos)
    skill: dict | None = None  # skill.activated: {name, tier, path, description}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REDACT_PATTERN = re.compile(r"key|token|secret|password|auth|credential", re.IGNORECASE)


def _redact(args: dict) -> dict:
    """Redact sensitive keys and truncate long string values."""
    out = {}
    for k, v in args.items():
        if _REDACT_PATTERN.search(k):
            out[k] = "[redacted]"
        elif isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + "..."
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_text(content) -> str:
    """Extract plain text from various LangChain content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content) if content else ""


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


@activity.defn
async def run_deep_agent(input: AgentInput) -> str:
    """
    Run the Deep Agent for a user message. Publishes progress events via
    WorkflowStream so the FastAPI layer can forward them to the client.
    """
    # Artifact directory per run. Carried in the per-run RunContext (below)
    # rather than a process-global env var, so concurrent runs stay isolated.
    artifact_dir = os.path.join(
        os.environ.get("ARTIFACT_BASE", "./artifacts"),
        input.run_id,
    )
    os.makedirs(artifact_dir, exist_ok=True)

    # Sequence counter
    _seq = 0

    def next_seq() -> int:
        nonlocal _seq
        s = _seq
        _seq += 1
        return s

    # Connect to the workflow stream to publish progress
    stream_client = WorkflowStreamClient.from_within_activity()
    async with stream_client:
        progress = stream_client.topic("progress", type=AgentProgress)

        # --- run_start ---
        progress.publish(
            AgentProgress(
                seq=next_seq(),
                ts=_now_iso(),
                run_id=input.run_id,
                type="run_start",
                label=input.user_message,
            )
        )

        # Create and invoke the agent, with a persistent conversation
        # checkpointer so turns sharing a thread_id share memory. SQLite file
        # persists across restarts; swap to PostgresSaver in Bucket B.
        from agent.core import create_agent
        from agent.context import RunContext, set_run_context
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        checkpoint_path = os.path.join(
            os.environ.get("ARTIFACT_BASE", "./artifacts"), ".checkpoints.sqlite"
        )
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(checkpoint_path)
        checkpointer = await _checkpointer_cm.__aenter__()
        agent = create_agent(checkpointer=checkpointer)

        activity.heartbeat("invoking agent")

        # Track tool timings: run_id -> monotonic start time
        tool_timers: dict[str, float] = {}
        plan_step_ids: set[str] = set()  # write_todos steps shown as plan, not tool
        final_response = ""
        # Coalesce llm_token events: batch text before publishing
        token_buffer = ""
        last_token_time = 0.0
        TOKEN_FLUSH_INTERVAL = 0.05  # seconds — flush tokens faster for snappier UI

        # Wire up live progress callback so tools can stream to the WS
        async def _on_tool_progress(label: str, tool_name: str):
            active_step_id = next(iter(tool_timers), None)
            progress.publish(
                AgentProgress(
                    seq=next_seq(),
                    ts=_now_iso(),
                    run_id=input.run_id,
                    type="tool_progress",
                    label=label,
                    step_id=active_step_id,
                    tool=tool_name,
                )
            )

        # Emit file.created at write time (tools call this as they save files).
        async def _on_file(filename: str):
            progress.publish(
                AgentProgress(
                    seq=next_seq(),
                    ts=_now_iso(),
                    run_id=input.run_id,
                    type="file",
                    label=f"Created: {filename}",
                    artifacts=[filename],
                )
            )

        # Bind this run's context to the current task. Isolated per activity —
        # concurrent runs no longer share ARTIFACT_DIR or the progress callback.
        set_run_context(
            RunContext(
                run_id=input.run_id,
                artifact_dir=artifact_dir,
                progress_cb=_on_tool_progress,
                file_cb=_on_file,
                thread_id=input.thread_id,
                user_id=input.user_id,
                org_id=input.org_id,
            )
        )

        def flush_tokens():
            nonlocal token_buffer
            if token_buffer:
                progress.publish(
                    AgentProgress(
                        seq=next_seq(),
                        ts=_now_iso(),
                        run_id=input.run_id,
                        type="llm_token",
                        label=token_buffer,
                    )
                )
                token_buffer = ""

        try:
            _config = {"recursion_limit": max(1, int(input.recursion_limit or 30))}
            if input.thread_id:
                _config["configurable"] = {"thread_id": input.thread_id}
            # Seed Agent Skills into the virtual FS (StateBackend reads the
            # `files` state channel): built-ins from disk + enabled AND
            # trusted org/user rows from the skill registry, re-read fresh
            # each run, narrowed to THIS run's tenant (this org's org rows +
            # this member's user rows) using only the identity carried in
            # AgentInput. The channel's dict-merge reducer refreshes skill
            # files in ongoing threads. scripts/ are never seeded
            # (instruction-only v1).
            from agent.skills import seed_files, skill_index
            from deepagents.backends.utils import create_file_data

            skill_seed = seed_files(user_id=input.user_id, org_id=input.org_id)
            skills_by_path = skill_index(skill_seed)
            skills_activated: set[str] = set()  # dedupe skill.activated per run

            # Continuing a thread: any SKILL.md the agent read on an earlier
            # turn is still in its checkpointed message history, so it stays
            # in force without being re-read — which means no read_file, and
            # so no skill.activated event. Announce those carried-over skills
            # up front so the UI shows what's shaping this turn. Only skills
            # still seeded for THIS run's tenant count (a skill disabled or
            # untrusted since then is not re-announced).
            if input.thread_id:
                try:
                    snap = await agent.aget_state(_config)
                    for msg in (snap.values or {}).get("messages", []) or []:
                        for tc in getattr(msg, "tool_calls", None) or []:
                            if tc.get("name") != "read_file":
                                continue
                            path = str((tc.get("args") or {}).get("file_path", ""))
                            info = skills_by_path.get(path)
                            if info and path not in skills_activated:
                                skills_activated.add(path)
                                progress.publish(
                                    AgentProgress(
                                        seq=next_seq(),
                                        ts=_now_iso(),
                                        run_id=input.run_id,
                                        type="skill",
                                        label=f"Skill in context: {info['name']}",
                                        skill={**info, "path": path},
                                    )
                                )
                except Exception as e:  # never let a UX hint break a run
                    logger.warning("carried-over skill scan failed: %s", e)
            async for ev in agent.astream_events(
                {
                    "messages": [{"role": "user", "content": input.user_message}],
                    # The files channel holds FileData dicts, not raw strings.
                    "files": {p: create_file_data(c) for p, c in skill_seed.items()},
                },
                version="v2",
                config=_config,
            ):
                activity.heartbeat("processing")
                event_type = ev.get("event", "")
                name = ev.get("name", "")
                run_id = ev.get("run_id", "")
                data = ev.get("data", {})

                # --- llm_token ---
                if event_type == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk:
                        text = _extract_text(getattr(chunk, "content", ""))
                        if text:
                            final_response += text
                            token_buffer += text
                            now = time.monotonic()
                            if now - last_token_time >= TOKEN_FLUSH_INTERVAL:
                                flush_tokens()
                                last_token_time = now

                # --- tool_start ---
                elif event_type == "on_tool_start":
                    flush_tokens()
                    tool_name = name
                    raw_args = data.get("input", {})
                    args = _redact(raw_args) if isinstance(raw_args, dict) else {}
                    # write_todos is the plan tool — emit a structured
                    # plan.snapshot instead of a generic tool block, and record
                    # the step id so its tool_end is suppressed too.
                    if tool_name == "write_todos":
                        todos = raw_args.get("todos", []) if isinstance(raw_args, dict) else []
                        plan_step_ids.add(run_id)
                        progress.publish(
                            AgentProgress(
                                seq=next_seq(),
                                ts=_now_iso(),
                                run_id=input.run_id,
                                type="plan",
                                label="Updated plan",
                                todos=todos if isinstance(todos, list) else [],
                            )
                        )
                    else:
                        # A read_file on a seeded SKILL.md is a skill
                        # activation (progressive disclosure stage 2) — emit
                        # skill.activated ahead of the tool block, once per
                        # skill per run.
                        if tool_name == "read_file" and isinstance(raw_args, dict):
                            skill_path = str(raw_args.get("file_path", ""))
                            info = skills_by_path.get(skill_path)
                            if info and skill_path not in skills_activated:
                                skills_activated.add(skill_path)
                                progress.publish(
                                    AgentProgress(
                                        seq=next_seq(),
                                        ts=_now_iso(),
                                        run_id=input.run_id,
                                        type="skill",
                                        label=f"Skill activated: {info['name']}",
                                        skill={**info, "path": skill_path},
                                    )
                                )
                        tool_timers[run_id] = time.monotonic()
                        progress.publish(
                            AgentProgress(
                                seq=next_seq(),
                                ts=_now_iso(),
                                run_id=input.run_id,
                                type="tool_start",
                                label=f"Using tool: {tool_name}",
                                step_id=run_id,
                                tool=tool_name,
                                args=args,
                            )
                        )

                # --- tool_end ---
                elif event_type == "on_tool_end":
                    # write_todos was surfaced as a plan.snapshot, not a tool.
                    if run_id in plan_step_ids:
                        plan_step_ids.discard(run_id)
                    else:
                        tool_name = name
                        output = data.get("output", "")
                        if hasattr(output, "content"):
                            output = output.content
                        output_str = str(output) if output else ""
                        preview = output_str[:500] if output_str else None

                        start_time = tool_timers.pop(run_id, None)
                        duration = (
                            int((time.monotonic() - start_time) * 1000) if start_time else None
                        )

                        progress.publish(
                            AgentProgress(
                                seq=next_seq(),
                                ts=_now_iso(),
                                run_id=input.run_id,
                                type="tool_end",
                                label=f"Finished: {tool_name}",
                                step_id=run_id,
                                tool=tool_name,
                                output_preview=preview,
                                duration_ms=duration,
                            )
                        )

                # --- tool_progress (custom events from inside tools) ---
                elif event_type == "on_custom_event":
                    if name == "tool_progress":
                        label = data.get("label", "") if isinstance(data, dict) else str(data)
                        tool_name = data.get("tool", None) if isinstance(data, dict) else None
                        # Find the active step_id from tool_timers
                        active_step_id = next(iter(tool_timers), None)
                        progress.publish(
                            AgentProgress(
                                seq=next_seq(),
                                ts=_now_iso(),
                                run_id=input.run_id,
                                type="tool_progress",
                                label=label,
                                step_id=active_step_id,
                                tool=tool_name,
                            )
                        )

                # (Plan snapshots are emitted from the write_todos tool_start
                # above, with structured todos — no string-dump chain handler.)

            # Flush any remaining tokens
            flush_tokens()

        except asyncio.CancelledError:
            # Phase 2: cancellation support
            progress.publish(
                AgentProgress(
                    seq=next_seq(),
                    ts=_now_iso(),
                    run_id=input.run_id,
                    type="cancelled",
                    label="Run cancelled by user",
                )
            )
            raise
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            progress.publish(
                AgentProgress(
                    seq=next_seq(),
                    ts=_now_iso(),
                    run_id=input.run_id,
                    type="error",
                    label=f"{type(e).__name__}: {str(e)[:300]}",
                )
            )
            raise  # re-raise so Temporal's retry policy can act
        finally:
            # Close the checkpointer connection whether the run succeeded,
            # was cancelled, or errored (and retries).
            await _checkpointer_cm.__aexit__(None, None, None)

        # List final artifacts by scanning the directory
        produced = []
        if os.path.isdir(artifact_dir):
            produced = [f for f in os.listdir(artifact_dir) if not f.startswith("~$")]
        for fname in produced:
            progress.publish(
                AgentProgress(
                    seq=next_seq(),
                    ts=_now_iso(),
                    run_id=input.run_id,
                    type="artifact",
                    label=f"Produced: {fname}",
                    artifacts=[fname],
                )
            )

        # --- done ---
        progress.publish(
            AgentProgress(
                seq=next_seq(),
                ts=_now_iso(),
                run_id=input.run_id,
                type="done",
                label=final_response[:500] if final_response else "Task completed",
                artifacts=produced,
            )
        )

    # No global cleanup needed: RunContext is a task-scoped ContextVar and is
    # discarded when this activity's task ends.
    return final_response or f"Task completed. Artifacts: {produced}"

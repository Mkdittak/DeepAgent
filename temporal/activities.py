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


@dataclass
class AgentProgress:
    seq: int                              # monotonic within a run, starts at 0
    ts: str                               # ISO-8601 UTC
    run_id: str
    type: str                             # run_start, plan, llm_token, tool_start, tool_progress, tool_end, artifact, error, cancelled, done
    label: str                            # human-readable one-liner for the UI
    step_id: str | None = None            # correlates tool_start with tool_end
    tool: str | None = None
    args: dict | None = None              # redacted; see _redact
    output_preview: str | None = None     # truncated to 500 chars
    duration_ms: int | None = None        # set on tool_end
    artifacts: list[str] = field(default_factory=list)


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
    # Set artifact directory per run
    artifact_dir = os.path.join(
        os.environ.get("ARTIFACT_BASE", "./artifacts"),
        input.run_id,
    )
    os.makedirs(artifact_dir, exist_ok=True)
    os.environ["ARTIFACT_DIR"] = artifact_dir

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
        progress.publish(AgentProgress(
            seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
            type="run_start",
            label=input.user_message,
        ))

        # Create and invoke the agent
        from agent.core import create_agent
        from agent.tools import set_progress_callback
        agent = create_agent()

        activity.heartbeat("invoking agent")

        # Track tool timings: run_id -> monotonic start time
        tool_timers: dict[str, float] = {}
        final_response = ""
        # Coalesce llm_token events: batch text before publishing
        token_buffer = ""
        last_token_time = 0.0
        TOKEN_FLUSH_INTERVAL = 0.05  # seconds — flush tokens faster for snappier UI

        # Wire up live progress callback so tools can stream to the WS
        async def _on_tool_progress(label: str, tool_name: str):
            active_step_id = next(iter(tool_timers), None)
            progress.publish(AgentProgress(
                seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                type="tool_progress",
                label=label,
                step_id=active_step_id,
                tool=tool_name,
            ))

        set_progress_callback(_on_tool_progress)

        def flush_tokens():
            nonlocal token_buffer
            if token_buffer:
                progress.publish(AgentProgress(
                    seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                    type="llm_token",
                    label=token_buffer,
                ))
                token_buffer = ""

        try:
            async for ev in agent.astream_events(
                {"messages": [{"role": "user", "content": input.user_message}]},
                version="v2",
                config={"recursion_limit": 30},
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
                    tool_timers[run_id] = time.monotonic()
                    progress.publish(AgentProgress(
                        seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                        type="tool_start",
                        label=f"Using tool: {tool_name}",
                        step_id=run_id,
                        tool=tool_name,
                        args=args,
                    ))

                # --- tool_end ---
                elif event_type == "on_tool_end":
                    tool_name = name
                    output = data.get("output", "")
                    if hasattr(output, "content"):
                        output = output.content
                    output_str = str(output) if output else ""
                    preview = output_str[:500] if output_str else None

                    start_time = tool_timers.pop(run_id, None)
                    duration = int((time.monotonic() - start_time) * 1000) if start_time else None

                    progress.publish(AgentProgress(
                        seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                        type="tool_end",
                        label=f"Finished: {tool_name}",
                        step_id=run_id,
                        tool=tool_name,
                        output_preview=preview,
                        duration_ms=duration,
                    ))

                # --- tool_progress (custom events from inside tools) ---
                elif event_type == "on_custom_event":
                    if name == "tool_progress":
                        label = data.get("label", "") if isinstance(data, dict) else str(data)
                        tool_name = data.get("tool", None) if isinstance(data, dict) else None
                        # Find the active step_id from tool_timers
                        active_step_id = next(iter(tool_timers), None)
                        progress.publish(AgentProgress(
                            seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                            type="tool_progress",
                            label=label,
                            step_id=active_step_id,
                            tool=tool_name,
                        ))

                # --- plan (todo list updates) ---
                elif event_type == "on_chain_end" and "todo" in name.lower():
                    output = data.get("output", "")
                    label = str(output)[:500] if output else "Updated plan"
                    progress.publish(AgentProgress(
                        seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                        type="plan",
                        label=label,
                    ))

            # Flush any remaining tokens
            flush_tokens()

        except asyncio.CancelledError:
            # Phase 2: cancellation support
            progress.publish(AgentProgress(
                seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                type="cancelled",
                label="Run cancelled by user",
            ))
            raise
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            progress.publish(AgentProgress(
                seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                type="error",
                label=f"{type(e).__name__}: {str(e)[:300]}",
            ))
            raise  # re-raise so Temporal's retry policy can act

        # List final artifacts by scanning the directory
        produced = []
        if os.path.isdir(artifact_dir):
            produced = [
                f for f in os.listdir(artifact_dir) if not f.startswith("~$")
            ]
        for fname in produced:
            progress.publish(AgentProgress(
                seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
                type="artifact",
                label=f"Produced: {fname}",
                artifacts=[fname],
            ))

        # --- done ---
        progress.publish(AgentProgress(
            seq=next_seq(), ts=_now_iso(), run_id=input.run_id,
            type="done",
            label=final_response[:500] if final_response else "Task completed",
            artifacts=produced,
        ))

    # Clean up callback
    set_progress_callback(None)
    return final_response or f"Task completed. Artifacts: {produced}"



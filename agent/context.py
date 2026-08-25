"""Per-run context, isolated across concurrent activities.

Replaces the former process-global state (`os.environ["ARTIFACT_DIR"]` and the
module-level `_progress_cb`), which corrupted whenever two runs executed on one
worker at the same time.

A `contextvars.ContextVar` is the right primitive: each Temporal activity runs
as its own asyncio task, and a ContextVar set at the top of the activity is
copied into that task's children only — so two concurrent runs each see their
own `RunContext` with no cross-talk.

`thread_id` is carried here too so conversational memory (M0) flows down the
same path without adding a second plumbing change.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

ProgressCallback = Callable[[str, str], Awaitable[None]]
FileCallback = Callable[[str], Awaitable[None]]


@dataclass
class RunContext:
    run_id: str
    artifact_dir: str
    progress_cb: Optional[ProgressCallback] = None
    file_cb: Optional[FileCallback] = None  # emits file.created at write time
    thread_id: Optional[str] = None  # set by the memory step (M0)


_run_context: contextvars.ContextVar[Optional[RunContext]] = contextvars.ContextVar(
    "run_context", default=None
)


def set_run_context(ctx: RunContext) -> None:
    """Bind the current run's context to this task."""
    _run_context.set(ctx)


def get_run_context() -> Optional[RunContext]:
    """Return the current run's context, or None outside a run."""
    return _run_context.get()

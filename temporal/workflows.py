"""
Temporal workflow: one workflow per user chat request.
Uses WorkflowStream to publish agent progress events that the FastAPI layer subscribes to.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib.workflow_streams import WorkflowStream
from temporalio.workflow import ActivityCancellationType

# Activity import is deferred via sandbox-safe import
with workflow.unsafe.imports_passed_through():
    from temporal.activities import run_deep_agent, AgentInput, AgentProgress


@dataclass
class WorkflowInput:
    """Input to the agent workflow.

    user_id/org_id are the identity the API resolved ONCE from the caller's
    Stytch session (backend/auth.py). The worker trusts these values and never
    re-derives identity from anything a client sent. None = pre-auth run
    (AUTH_ENABLED=false), which seeds skills exactly as before.
    """
    run_id: str
    user_message: str
    thread_id: str | None = None  # conversation thread for multi-turn memory (M0)
    user_id: str | None = None    # Stytch member_id, resolved in the API
    org_id: str | None = None     # Stytch organization_id, resolved in the API
    recursion_limit: int = 30     # agent step budget; 15 proved too low (planning + middleware steps count)


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
            AgentInput(
                run_id=input.run_id,
                user_message=input.user_message,
                thread_id=input.thread_id,
                user_id=input.user_id,
                org_id=input.org_id,
                recursion_limit=input.recursion_limit,
            ),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=3,
            ),
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        # The activity already publishes a "done" event. The workflow publishes
        # nothing extra — the activity owns the full event stream.
        self.done = True
        self.result = result
        return result

    @workflow.query
    def is_done(self) -> bool:
        return self.done

    @workflow.query
    def get_result(self) -> str | None:
        return self.result

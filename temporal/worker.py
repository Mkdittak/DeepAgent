"""
Temporal worker — run this process to pick up agent workflows.

Usage:
    python -m temporal.worker
"""

import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

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

    # Cap concurrent activities explicitly. Each run drives LLM + tool calls,
    # so this bounds resource use; override with WORKER_MAX_CONCURRENT_ACTIVITIES.
    max_concurrent = int(os.environ.get("WORKER_MAX_CONCURRENT_ACTIVITIES", "10"))

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentWorkflow],
        activities=[run_deep_agent],
        max_concurrent_activities=max_concurrent,
    )
    print(f"max_concurrent_activities={max_concurrent}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

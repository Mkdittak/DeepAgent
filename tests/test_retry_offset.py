"""Real-library proof: across a forced activity RETRY (seq restarts at 0), the
durable WorkflowStream assigns fresh, monotonic offsets, so offset-dedup keeps
both attempts (no drop/splice) where seq-dedup could not. Real temporalio, no LLM.
"""
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporalio.contrib.workflow_streams import WorkflowStream, WorkflowStreamClient


@dataclass
class Ev:
    seq: int
    text: str


@activity.defn
async def publish_activity() -> str:
    attempt = activity.info().attempt
    sc = WorkflowStreamClient.from_within_activity()
    async with sc:
        topic = sc.topic("progress", type=Ev)
        for seq in range(3):  # seq RESTARTS at 0 every attempt
            topic.publish(Ev(seq=seq, text=f"attempt{attempt}-seq{seq}"), force_flush=True)
        await sc.flush()
        if attempt == 1:
            raise RuntimeError("forced retry: simulates worker death mid-generation")
    return "done"


@workflow.defn
class RetryStreamWorkflow:
    @workflow.init
    def __init__(self) -> None:
        self.stream = WorkflowStream()
        self.stream.topic("progress", type=Ev)

    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            publish_activity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=200),
                maximum_attempts=2,
            ),
        )


async def main():
    import uuid
    from temporalio.client import Client
    from temporalio.worker import Worker

    client = await Client.connect("localhost:7233")
    wf_id = f"retry-proof-{uuid.uuid4().hex[:8]}"
    task_queue = "retry-proof-q"

    async with Worker(
        client, task_queue=task_queue,
        workflows=[RetryStreamWorkflow], activities=[publish_activity],
    ):
        await client.start_workflow(RetryStreamWorkflow.run, id=wf_id, task_queue=task_queue)
        sc = WorkflowStreamClient.create(client, wf_id)
        collected = []
        async for item in sc.subscribe(["progress"], result_type=Ev):
            collected.append((item.offset, item.data.seq, item.data.text))
            if len(collected) >= 6:
                break

    offsets = [o for o, _, _ in collected]
    seqs = [s for _, s, _ in collected]
    print("collected (offset, seq, text):")
    for row in collected:
        print("   ", row)
    print("offsets:", offsets)
    print("seqs   :", seqs)
    print("offsets strictly increasing & unique:",
          offsets == sorted(offsets) and len(set(offsets)) == len(offsets))
    print("seq DID restart across the retry (the old bug's trigger):", seqs == [0, 1, 2, 0, 1, 2])
    seen = set(); drop_seq = sum(1 for s in seqs if (s in seen) or (seen.add(s) or False))
    seeo = set(); drop_off = sum(1 for o in offsets if (o in seeo) or (seeo.add(o) or False))
    print(f"events a SEQ-dedup client DROPS: {drop_seq}  (this was the corruption)")
    print(f"events the OFFSET-dedup client DROPS: {drop_off}  (clean: nothing lost)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

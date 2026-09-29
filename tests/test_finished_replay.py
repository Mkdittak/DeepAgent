import sys, time, asyncio

sys.path.insert(0, ".")
from sse_client import start_run, stream
from temporalio.client import Client


async def wait_done(wf_id):
    c = await Client.connect("localhost:7233")
    h = c.get_workflow_handle(wf_id)
    for _ in range(60):
        d = await h.describe()
        if int(d.status) != 1:  # 1 = RUNNING
            return int(d.status)
        await asyncio.sleep(1)
    return -1


r = start_run("Say the word blue and nothing else.")
run_id, wf_id = r["run_id"], r["workflow_id"]
status = asyncio.run(wait_done(wf_id))
print("workflow status after completion (2=COMPLETED):", status)

# Past Runs -> Reconnect on a run that is ALREADY finished: fresh SSE from 0.
replay = stream(run_id, last_event_id=None)
print("events delivered on reconnect to a FINISHED run:", len(replay))
print("=> user sees:", "content" if replay else "EMPTY (nothing replays)")

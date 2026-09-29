import sys, time, asyncio

sys.path.insert(0, ".")
from sse_client import start_run, stream
from temporalio.client import Client


async def wait_done(wf_id):
    c = await Client.connect("localhost:7233")
    h = c.get_workflow_handle(wf_id)
    for _ in range(90):
        d = await h.describe()
        if int(d.status) != 1:
            return int(d.status)
        await asyncio.sleep(1)
    return -1


# 1) Run it and watch live (this is what persists events to JSONL).
r = start_run("Say the word 'green' and then say 'done'.")
run_id, wf_id = r["run_id"], r["workflow_id"]
live = stream(run_id)
print("LIVE: events=%d, terminal=%s" % (len(live), live[-1]["type"] if live else None))

# 2) Ensure the workflow is fully COMPLETED.
status = asyncio.run(wait_done(wf_id))
print("workflow status (2=COMPLETED):", status)

# 3) Past Runs -> Reconnect: a FRESH client (empty state, no last-event-id),
#    exactly like opening it in a fresh browser profile.
time.sleep(1)
replay = stream(run_id, last_event_id=None)
rtypes = [e["type"] for e in replay]
print("REPLAY: events=%d types=%s" % (len(replay), rtypes))
print(
    "full conversation replays (has run.started + text + run.finished):",
    "run.started" in rtypes and "run.finished" in rtypes and any(t == "text.delta" for t in rtypes),
)
print("PROOF (Past Runs finished-run replay):", len(replay) > 0 and rtypes[-1] == "run.finished")

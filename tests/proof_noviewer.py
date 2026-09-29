import sys, asyncio

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


# Start a run and DO NOT watch it live at all. Only the backend's background
# persister sees it. This is the API-started / never-opened case.
r = start_run("Say the word 'purple' then say 'ok'.")
run_id, wf_id = r["run_id"], r["workflow_id"]
status = asyncio.run(wait_done(wf_id))
print("workflow status (2=COMPLETED):", status, "(no live viewer attached)")

# Now open it from Past Runs for the first time ever.
replay = stream(run_id)
rtypes = [e["type"] for e in replay]
print("REPLAY of a never-watched run:", len(replay), rtypes)
print(
    "PROOF (background persister covers unwatched runs):",
    len(replay) > 0 and rtypes[-1] == "run.finished",
)

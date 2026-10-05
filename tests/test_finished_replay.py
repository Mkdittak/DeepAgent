import asyncio
import socket
import sys

sys.path.insert(0, ".")
from sse_client import BASE, start_run, stream
from temporalio.client import Client


def _backend_up() -> bool:
    host, _, port = BASE.removeprefix("http://").partition(":")
    try:
        with socket.create_connection((host, int(port or 80)), timeout=1):
            return True
    except OSError:
        return False


# Full-stack proof: needs Temporal + worker + backend (tests/README.md, section 5).
if not _backend_up():
    if "pytest" in sys.modules:
        import pytest

        pytest.skip(f"needs the full stack running ({BASE} not reachable)", allow_module_level=True)
    raise SystemExit(f"backend not reachable at {BASE}; bring the stack up first")


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

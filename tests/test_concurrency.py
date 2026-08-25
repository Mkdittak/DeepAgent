import asyncio
import os
import tempfile

from agent.context import RunContext, set_run_context
from agent import tools


async def one_run(run_id: str, base: str, events: list):
    artifact_dir = os.path.join(base, run_id)
    os.makedirs(artifact_dir, exist_ok=True)

    async def progress_cb(label, tool):
        events.append((run_id, label))  # collector unique to this run

    # Each task sets its OWN context.
    set_run_context(RunContext(run_id=run_id, artifact_dir=artifact_dir, progress_cb=progress_cb))

    # Yield control so the two runs interleave (forces the race the old
    # globals would lose).
    await asyncio.sleep(0)
    await tools._emit(f"hello from {run_id}", "web_search")
    await asyncio.sleep(0)
    # generate_html reads _artifact_dir() from the per-run context.
    msg = await tools.generate_html(title=run_id, body_html=f"<p>{run_id}</p>")
    await asyncio.sleep(0)
    await tools._emit(f"bye from {run_id}", "web_search")
    return msg, artifact_dir


async def main():
    base = tempfile.mkdtemp()
    events_a, events_b = [], []
    (msg_a, dir_a), (msg_b, dir_b) = await asyncio.gather(
        one_run("run-A", base, events_a),
        one_run("run-B", base, events_b),
    )

    file_a = os.path.join(dir_a, "index.html")
    file_b = os.path.join(dir_b, "index.html")
    content_a = open(file_a, encoding="utf-8").read()
    content_b = open(file_b, encoding="utf-8").read()

    print("A file in A's dir:", os.path.isfile(file_a), "and contains A:", "run-A" in content_a)
    print("B file in B's dir:", os.path.isfile(file_b), "and contains B:", "run-B" in content_b)
    print("no cross-contamination:", "run-B" not in content_a and "run-A" not in content_b)
    print("A progress events all belong to A:", all(r == "run-A" for r, _ in events_a), events_a)
    print("B progress events all belong to B:", all(r == "run-B" for r, _ in events_b), events_b)


asyncio.run(main())

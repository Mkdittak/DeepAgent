import sys
sys.path.insert(0, ".")
from sse_client import start_run, stream

r = start_run("Say hello in exactly one word.")
print("started:", r)
types = []
def show(env):
    t = env["type"]
    types.append(t)
    extra = env.get("text") or env.get("prompt") or env.get("state") or env.get("name") or ""
    print(f"  off={env['offset']:>3} v={env['v']} uid={env['user_id']} type={t:16} {str(extra)[:40]}")

events = stream(r["run_id"], on_event=show)
print("total events:", len(events))
print("distinct types:", sorted(set(types)))
print("terminal:", events[-1]["type"], events[-1].get("state"))
print("SMOKE PASS:", events[-1]["type"] == "run.finished")

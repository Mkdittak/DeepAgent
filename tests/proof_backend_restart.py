import sys, time, subprocess, os, json, asyncio, urllib.request
sys.path.insert(0, ".")
from sse_client import start_run, stream, BASE
from temporalio.client import Client

PROJ = r"C:\Mukund's Projects\DeepAgent"
PY = os.path.join(PROJ, ".venv", "Scripts", "python.exe")
EVENTS = os.path.join(PROJ, "artifacts", ".events")


def uvicorn_pids():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'uvicorn' } | ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def start_backend():
    return subprocess.Popen(
        [PY, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
        cwd=PROJ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def jsonl(run_id):
    p = os.path.join(EVENTS, run_id + ".jsonl")
    if not os.path.isfile(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


async def wait_done(wf):
    c = await Client.connect("localhost:7233")
    h = c.get_workflow_handle(wf)
    for _ in range(120):
        d = await h.describe()
        if int(d.status) != 1:
            return int(d.status)
        await asyncio.sleep(1)
    return -1


r = start_run("Write a very long, detailed 1500-word essay about the history of aviation.")
run_id, wf_id = r["run_id"], r["workflow_id"]
print("run:", run_id)

time.sleep(6)
partial = jsonl(run_id)
print("partial JSONL before restart: lines=%d, terminal=%s"
      % (len(partial), any(e["type"] == "run.finished" for e in partial)))

for pid in uvicorn_pids():
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
print("backend KILLED mid-run")
time.sleep(2)

start_backend()
for _ in range(30):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=2); break
    except Exception:
        time.sleep(1)
print("backend RESTARTED (startup recovery ran)")

status = asyncio.run(wait_done(wf_id))
print("workflow status (2=COMPLETED):", status)
time.sleep(4)  # let re-attached persister flush the terminal

final = jsonl(run_id)
has_terminal = any(e["type"] == "run.finished" for e in final)
has_notice = any("interrupted by a backend restart" in e.get("text", "") for e in final)
replay = stream(run_id)
print("final JSONL: lines=%d, run.finished=%s, incompleteness-notice=%s"
      % (len(final), has_terminal, has_notice))
print("backfilled beyond partial:", len(final) > len(partial))
print("reconnect replay: events=%d terminal=%s"
      % (len(replay), replay[-1]["type"] if replay else None))
print("PROOF (running-at-restart -> FULL backfill, real terminal, NO notice):",
      has_terminal and not has_notice and len(final) > len(partial)
      and bool(replay) and replay[-1]["type"] == "run.finished")

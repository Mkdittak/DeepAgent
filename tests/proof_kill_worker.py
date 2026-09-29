import sys, time, threading, subprocess, os

sys.path.insert(0, ".")
from sse_client import start_run, stream

PROJ = r"C:\Mukund's Projects\DeepAgent"
PY = os.path.join(PROJ, ".venv", "Scripts", "python.exe")


def worker_pids():
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'temporal.worker' } | "
            "ForEach-Object { $_.ProcessId }",
        ],
        capture_output=True,
        text=True,
    ).stdout
    return [int(x) for x in out.split()]


r = start_run(
    "Write a detailed 300-word adventure story about a lighthouse keeper who discovers a secret."
)
run_id = r["run_id"]
print("run:", run_id, flush=True)

collected = []
done = threading.Event()


def reader():
    try:
        collected.extend(stream(run_id, timeout=420))
    finally:
        done.set()


threading.Thread(target=reader, daemon=True).start()

# Wait until mid-generation (a couple of text deltas).
t0 = time.time()
while time.time() - t0 < 30:
    if sum(1 for e in collected if e.get("type") == "text.delta") >= 2:
        break
    time.sleep(0.3)
pre = [(e["offset"], e["type"]) for e in collected]
print("pre-kill events:", pre, flush=True)

# Hard-kill the worker mid-run.
pids = worker_pids()
for pid in pids:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
print("killed worker pids:", pids, flush=True)
time.sleep(2)

# Restart the worker so Temporal can retry the activity (after heartbeat timeout).
env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
subprocess.Popen(
    [PY, "-u", "-m", "temporal.worker"],
    cwd=PROJ,
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print("restarted worker; waiting for retry (heartbeat timeout ~5 min)...", flush=True)

done.wait(timeout=400)

offs = [e["offset"] for e in collected]
run_starts = [e for e in collected if e.get("type") == "run.started"]
mono_unique = offs == sorted(offs) and len(set(offs)) == len(offs)
print("=== RESULT ===", flush=True)
print("total events:", len(collected), flush=True)
print("offsets:", offs, flush=True)
print("offsets strictly monotonic & unique (no collision/splice):", mono_unique, flush=True)
print("run.started count (>=2 means retry rendered as a fresh turn):", len(run_starts), flush=True)
print("terminal:", collected[-1]["type"] if collected else None, flush=True)
print(
    "PROOF 1 (kill worker -> clean stream):",
    mono_unique and len(collected) > len(pre) and (collected[-1]["type"] == "run.finished"),
    flush=True,
)

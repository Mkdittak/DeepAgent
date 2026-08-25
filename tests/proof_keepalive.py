import sys, time, threading, urllib.request
sys.path.insert(0, ".")
from sse_client import start_run, BASE

# Start a longer-running task so the workflow stays RUNNING during the test.
r = start_run("Write a very long and detailed 1500-word essay about the entire "
              "history of the Roman Empire: founding, republic, empire, and fall.")
run_id = r["run_id"]
print("run:", run_id)
time.sleep(2)  # let it get going / stay running

# Connect asking for an offset far beyond anything produced, so the stream has
# NO events to send and must rely on keepalive pings to stay open.
req = urllib.request.Request(f"{BASE}/runs/{run_id}/stream",
                             headers={"Last-Event-ID": "9999999"})
pings = 0
data_lines = 0
t0 = time.time()
with urllib.request.urlopen(req, timeout=60) as resp:
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith(": ping"):
            pings += 1
            print(f"  t={time.time()-t0:4.0f}s  <- keepalive ping")
        elif line.startswith("data:"):
            data_lines += 1
        if time.time() - t0 > 34:  # ~2 keepalive intervals
            break

print("keepalive pings seen in ~34s:", pings)
print("PROOF (SSE keepalive):", pings >= 1)

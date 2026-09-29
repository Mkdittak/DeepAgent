import sys

sys.path.insert(0, ".")
from sse_client import start_run, stream

# A longer run (web search + generation) so it is still streaming on reconnect.
r = start_run("Search the web for facts about octopuses, then write a detailed 250-word summary.")
run_id = r["run_id"]
print("run:", run_id)

# --- Client connects, reads the first few events, then "refreshes" (disconnects) ---
first = stream(run_id, max_events=3)
first_offsets = [e["offset"] for e in first]
last_seen = max(first_offsets)
print("before refresh, offsets:", first_offsets, "-> last_seen =", last_seen)

# --- After refresh: reconnect with Last-Event-ID = last_seen ---
rest = stream(run_id, last_event_id=last_seen)
rest_offsets = [e["offset"] for e in rest]
print("after refresh, first offset:", rest_offsets[0], "count:", len(rest_offsets))

combined = first_offsets + rest_offsets
no_dup = len(combined) == len(set(combined))
contiguous = sorted(set(combined)) == list(range(min(combined), max(combined) + 1))
resume_after = rest_offsets[0] == last_seen + 1

print("resumed exactly at last_seen+1 (no replay of seen):", resume_after)
print("no duplicated offsets across the refresh:", no_dup)
print("full history contiguous, nothing lost:", contiguous)
print("reached terminal:", rest[-1]["type"] == "run.finished")
print("PROOF 2 (refresh resume, no dup):", resume_after and no_dup and contiguous)

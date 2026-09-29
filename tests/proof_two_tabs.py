import sys, threading

sys.path.insert(0, ".")
from sse_client import start_run, stream

r = start_run("Search the web for facts about volcanoes, then write a 200-word summary.")
run_id = r["run_id"]
print("run:", run_id)

results = {}


def tab(name):
    evs = stream(run_id)  # each tab subscribes independently from offset 0
    results[name] = [e["offset"] for e in evs]


# Two "browser tabs" watching the same run at the same time.
t1 = threading.Thread(target=tab, args=("tabA",))
t2 = threading.Thread(target=tab, args=("tabB",))
t1.start()
t2.start()
t1.join()
t2.join()

a, b = results["tabA"], results["tabB"]
print("tabA events:", len(a), "tabB events:", len(b))
same = set(a) == set(b)
both_terminal = len(a) > 0 and len(b) > 0
contiguous = sorted(set(a)) == list(range(0, max(a) + 1)) if a else False
print("both tabs saw the SAME offsets:", same)
print("both contiguous from 0:", contiguous)
print("PROOF 3 (two tabs stream correctly):", same and both_terminal and contiguous)

"""
Per-org daily run quota: the N+1th run in a day for one org -> 429 with a
reset time; other orgs unaffected; yesterday's rows don't count.

Run (repo root): .venv\\Scripts\\python.exe tests\\test_quota.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import Harness, check, finish  # noqa: E402

h = Harness()
c = h.c
m = h.m
N = 3
m.RUN_QUOTA_PER_ORG_PER_DAY = N

h.as_(h.A); check("run 1 (A) ok", c.post("/runs", json={"message": "1"}).status_code == 200)
h.as_(h.B); check("run 2 (B, same org) ok — cap is per ORG", c.post("/runs", json={"message": "2"}).status_code == 200)
h.as_(h.A); check("run 3 (A) ok", c.post("/runs", json={"message": "3"}).status_code == 200)

r = c.post("/runs", json={"message": "4"})
check(f"run {N+1} in org X -> 429", r.status_code == 429)
j = r.json()
check("429 body: limit/used", j.get("limit") == N and j.get("used") == N)
reset = datetime.fromisoformat(j["reset_at"])
now = datetime.now().astimezone()
check("429 body: reset_at is the next local midnight",
      reset > now and reset.hour == reset.minute == reset.second == 0 and (reset - now).total_seconds() <= 86400)
check("429 header: Retry-After ~ seconds to reset",
      abs(int(r.headers["retry-after"]) - int((reset - now).total_seconds())) <= 5)
check("no run was created for the rejected request", len(h.started) == N)
h.as_(h.B); check("B (same org) also blocked", c.post("/runs", json={"message": "5"}).status_code == 429)

h.as_(h.C); check("org Y unaffected", c.post("/runs", json={"message": "y1"}).status_code == 200)

# Rows from a previous day don't count against today.
for info in m.run_registry.values():
    if info.get("org_id") == "org-X":
        info["created_at"] = "2000-01-01T00:00:00+00:00"
h.as_(h.A); check("after the day rolls over, org X can run again", c.post("/runs", json={"message": "6"}).status_code == 200)

# _quota_status itself
used, reset_at = m._quota_status("org-X")
check("_quota_status counts only today's rows", used == 1)

finish()

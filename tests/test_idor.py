"""
IDOR: member B asking for member A's thread / run / stream / artifact / user
skill gets 404 — never 403, never data. Same for an admin in another org.

Run (repo root): .venv\\Scripts\\python.exe tests\\test_idor.py
Standalone: temp ARTIFACT_BASE, Temporal faked, AUTH_ENABLED=true.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import Harness, check, finish  # noqa: E402

h = Harness()
c = h.c

# A owns a run + thread + artifact + user skill.
h.as_(h.A)
r = h.run("A's private question")
run_a, thread_a = r["run_id"], r["thread_id"]
h.artifact(run_a, "secret.txt", "A's data")
skill_a = h.install("a-private", "user")

check("A sees own thread", c.get(f"/threads/{thread_a}").status_code == 200)
check("A can stream own run", c.get(f"/runs/{run_a}/stream").status_code == 200)
check("A can sign own artifact", c.get(f"/artifacts/{run_a}/secret.txt/sign").status_code == 200)

for label, p in (("B (same org, plain member)", h.B), ("C (other org, admin)", h.C)):
    h.as_(p)
    for name, resp in (
        ("GET /threads/{A}", c.get(f"/threads/{thread_a}")),
        ("PATCH /threads/{A}", c.patch(f"/threads/{thread_a}", json={"title": "pwned"})),
        ("DELETE /threads/{A}", c.delete(f"/threads/{thread_a}")),
        ("GET /runs/{A}/stream", c.get(f"/runs/{run_a}/stream")),
        ("POST /runs/{A}/cancel", c.post(f"/runs/{run_a}/cancel")),
        ("GET /artifacts/{A}/secret.txt/sign", c.get(f"/artifacts/{run_a}/secret.txt/sign")),
        ("GET /artifacts/{A}/secret.txt (unsigned)", c.get(f"/artifacts/{run_a}/secret.txt")),
        ("GET /skills/{A-user}", c.get(f"/skills/{skill_a}")),
        ("PATCH /skills/{A-user}", c.patch(f"/skills/{skill_a}", json={"enabled": True})),
        ("DELETE /skills/{A-user}", c.delete(f"/skills/{skill_a}")),
    ):
        check(f"{label}: {name} -> 404", resp.status_code == 404)
        check(f"{label}: {name} leaks nothing", "A's" not in resp.text and "pwned" not in resp.text)
    check(f"{label}: /threads listing excludes A", thread_a not in {t["thread_id"] for t in c.get("/threads").json()})
    check(f"{label}: /runs listing excludes A", run_a not in {x["run_id"] for x in c.get("/runs").json()})
    check(f"{label}: /skills listing excludes A's user skill", "a-private" not in h.skill_names())
    hijack = c.post("/runs", json={"message": "continue A's thread", "thread_id": thread_a}).json()
    check(f"{label}: continuing A's thread_id starts a FRESH thread", hijack["thread_id"] != thread_a)

# Nothing of A's was modified by the attempts above.
h.as_(h.A)
t = c.get(f"/threads/{thread_a}").json()
check("A's thread title unchanged", t["title"] == "A's private question")
check("A's thread not deleted", c.get(f"/threads/{thread_a}").status_code == 200)
check("A's thread has only A's run", [x["run_id"] for x in t["runs"]] == [run_a])
check("A's skill not enabled/deleted", c.get(f"/skills/{skill_a}").json()["enabled"] is False)

finish()

"""
AUTH_ENABLED=false is a true no-op: every endpoint behaves exactly as
pre-auth (single implicit user) — no scoping, no admin gate, no quota, no
signed URLs, no Stytch calls, null identity on new rows.

Data is created with the flag ON first (three tenants), then the flag is
flipped OFF and everything must be reachable by anyone, exactly as if the
rows had never carried identity.

Run (repo root): .venv\\Scripts\\python.exe tests\\test_flag_off.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import Harness, REAL_GET_PRINCIPAL, REAL_REVERIFY, check, finish  # noqa: E402

from starlette.requests import Request  # noqa: E402

from backend import auth  # noqa: E402

h = Harness()
c = h.c
m = h.m

# --- seed with the flag ON ---
h.as_(h.A)
ra = h.run("A's run"); run_a, thread_a = ra["run_id"], ra["thread_id"]
h.artifact(run_a, "a.html", "<b>a</b>")
skill_a_user = h.install("a-user", "user")
skill_x_org = h.install("x-org", "org")
h.as_(h.C)
rc = h.run("C's run"); thread_c = rc["thread_id"]
h.as_(h.B)
check("(flag on) B cannot see A's thread", c.get(f"/threads/{thread_a}").status_code == 404)
check("(flag on) B cannot trust org skill", c.patch(f"/skills/{skill_x_org}", json={"trust_state": "trusted"}).status_code == 403)

# --- flip OFF ---
h.set_auth(False)
auth._client = None  # any Stytch use from here on would rebuild the client; assert it doesn't
h.as_(h.B)  # whoever the override returns is irrelevant now

check("threads: everyone's threads listed", {thread_a, thread_c} <= {t["thread_id"] for t in c.get("/threads").json()})
check("threads: A's thread readable", c.get(f"/threads/{thread_a}").status_code == 200)
check("threads: A's thread renamable", c.patch(f"/threads/{thread_a}", json={"title": "renamed"}).status_code == 200)
check("runs: everyone's runs listed", run_a in {x["run_id"] for x in c.get("/runs").json()})
check("runs: A's run streamable", c.get(f"/runs/{run_a}/stream").status_code == 200)
check("runs: A's run cancellable", c.post(f"/runs/{run_a}/cancel").status_code == 200)
check("runs: continuing A's thread_id continues it", c.post("/runs", json={"message": "x", "thread_id": thread_a}).json()["thread_id"] == thread_a)
row = m.run_registry[h.started[-1].run_id]
check("runs: new registry row has NULL identity", row["user_id"] is None and row["org_id"] is None)
check("runs: WorkflowInput carries no identity", (h.started[-1].user_id, h.started[-1].org_id) == (None, None))
new_thread = c.post("/runs", json={"message": "fresh"}).json()["thread_id"]
check("threads: new thread row has NULL identity", h.store._threads[new_thread]["user_id"] is None)

check("skills: all tiers from all tenants listed", {"a-user", "x-org"} <= set(h.skill_names()))
check("skills: A's user skill readable", c.get(f"/skills/{skill_a_user}").status_code == 200)
auth.reverify_network = REAL_REVERIFY  # the real one: must short-circuit, never build a client
check("skills: org skill trust/enable needs no admin (no gate)", c.patch(f"/skills/{skill_x_org}", json={"trust_state": "trusted", "enabled": True}).status_code == 200)
check("skills: org write built no Stytch client (no network path)", auth._client is None)
new_skill = h.install("flag-off-skill", "user")
check("skills: new row has NULL identity", h.store._skills[new_skill]["user_id"] is None)
check("skills: dup name is a dup globally (pre-auth uniqueness)", c.post("/skills", json={"body": "---\nname: flag-off-skill\ndescription: d\n---\nb", "tier": "user"}).status_code == 409)

check("artifacts: unsigned URL serves", c.get(f"/artifacts/{run_a}/a.html").status_code == 200)
check("artifacts: traversal still blocked", c.get(f"/artifacts/{run_a}/..%2F..%2F.env").status_code == 404)
m.RUN_QUOTA_PER_ORG_PER_DAY = 0
check("quota: not enforced", c.post("/runs", json={"message": "unlimited"}).status_code == 200)

# The envelope keeps the pre-auth wire shape (null identity) for flag-off runs.
from temporal.activities import AgentProgress  # noqa: E402
env = m._v1_envelope(0, AgentProgress(seq=0, ts="t", run_id=h.started[-1].run_id, type="done", label="ok"), h.started[-1].run_id)
check("envelope: user_id/org_id null for flag-off runs", env["user_id"] is None and env["org_id"] is None)

# The real dependency + reverifier short-circuit without touching Stytch.
req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
check("get_principal -> LEGACY with no headers", asyncio.run(REAL_GET_PRINCIPAL(req)) == auth.LEGACY_PRINCIPAL)
check("reverify_network -> passthrough with no headers", asyncio.run(REAL_REVERIFY(req, h.B)) is h.B)
auth.require_role(h.B, auth.ADMIN_ROLE); check("require_role -> no-op for a plain member", True)
check("no Stytch client was built", auth._client is None)
check("_ident() is None (seam gets legacy behavior)", m._ident(h.A) is None)

finish()

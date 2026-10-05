"""
Admin gate: a plain member cannot trust / enable / delete an ORG skill (403);
an admin can. User-tier rows need only ownership. Org writes go through the
network-backed re-verification; user writes never do.

Also unit-tests the real auth.reverify_network against a fake Stytch client:
Stytch 403 -> our 403, Stytch 401/other -> 401, bearer/session-token identity
mismatch -> 401, missing X-Session-Token -> 401, success -> fresh Principal.

Run (repo root): .venv\\Scripts\\python.exe tests\\test_admin_gate.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import REAL_REVERIFY, Harness, check, finish
from fastapi import HTTPException
from starlette.requests import Request
from stytch.core.response_base import StytchError, StytchErrorDetails

from backend import auth


def test_admin_gate():
    h = Harness()
    c = h.c

    # --- route-level gate (reverify stubbed by the harness; role check is real) ---
    h.as_(h.B)
    org_skill = h.install("org-tool", "org")  # any member may PROPOSE an org skill
    check("member can install (propose) an org skill", org_skill is not None)
    check(
        "member: trust org skill -> 403",
        c.patch(f"/skills/{org_skill}", json={"trust_state": "trusted"}).status_code == 403,
    )
    check(
        "member: enable org skill -> 403",
        c.patch(f"/skills/{org_skill}", json={"enabled": True}).status_code == 403,
    )
    check("member: delete org skill -> 403", c.delete(f"/skills/{org_skill}").status_code == 403)
    check(
        "member: org skill still untrusted+disabled",
        (lambda s: s["trust_state"] == "untrusted" and s["enabled"] is False)(
            c.get(f"/skills/{org_skill}").json()
        ),
    )
    check("member: 403s never hit the network (role check first)", h.reverify_calls == [])

    user_skill = h.install("my-tool", "user")
    check(
        "member: trust own user skill -> 200 (ownership only)",
        c.patch(f"/skills/{user_skill}", json={"trust_state": "trusted"}).status_code == 200,
    )
    check(
        "member: enable own user skill -> 200",
        c.patch(f"/skills/{user_skill}", json={"enabled": True}).status_code == 200,
    )
    check("member: user-tier writes never reverify over the network", h.reverify_calls == [])
    check(
        "member: delete own user skill -> 200", c.delete(f"/skills/{user_skill}").status_code == 200
    )

    builtins = [s for s in c.get("/skills").json() if s["tier"] == "built-in"]
    if builtins:
        bid = builtins[0]["skill_id"]
        check(
            "member: toggle built-in (project-wide) -> 403",
            c.patch(f"/skills/{bid}", json={"enabled": False}).status_code == 403,
        )

    h.as_(h.A)
    r = c.patch(f"/skills/{org_skill}", json={"trust_state": "trusted", "enabled": True})
    check(
        "admin: trust+enable org skill -> 200", r.status_code == 200 and r.json()["enabled"] is True
    )
    check(
        "admin: org write went through network reverify",
        [p.user_id for p in h.reverify_calls] == ["member-A"],
    )
    h.reverify_calls.clear()
    check("admin: delete org skill -> 200", c.delete(f"/skills/{org_skill}").status_code == 200)
    check(
        "admin: org delete went through network reverify",
        [p.user_id for p in h.reverify_calls] == ["member-A"],
    )
    if builtins:
        check(
            "admin: toggle built-in -> 200",
            c.patch(f"/skills/{bid}", json={"enabled": False}).status_code == 200,
        )
        c.patch(f"/skills/{bid}", json={"enabled": True})
    check("admin: built-in toggle is a LOCAL role check (no network)", len(h.reverify_calls) == 1)

    # --- require_role directly ---
    try:
        auth.require_role(h.B, auth.ADMIN_ROLE)
        check("require_role member -> 403", False)
    except HTTPException as e:
        check("require_role member -> 403", e.status_code == 403)
    auth.require_role(h.A, auth.ADMIN_ROLE)
    check("require_role admin passes", True)

    # --- real reverify_network against a fake Stytch client ---
    class _MS:
        def __init__(self, member_id, organization_id, roles):
            self.member_id, self.organization_id, self.roles = member_id, organization_id, roles

    class _Resp:
        def __init__(self, ms):
            self.member_session = ms

    class _Sessions:
        def __init__(self):
            self.behavior = None
            self.calls = []

        async def authenticate_async(self, **kw):
            self.calls.append(kw)
            b = self.behavior
            if isinstance(b, Exception):
                raise b
            return b

    class _Client:
        def __init__(self):
            self.sessions = _Sessions()

    fake = _Client()
    auth._client = fake  # module singleton swapped for the fake

    def req(headers):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            }
        )

    def run(headers, principal):
        try:
            return asyncio.run(REAL_REVERIFY(req(headers), principal))
        except HTTPException as e:
            return e.status_code

    TOK = {"X-Session-Token": "sess-abc"}
    fake.sessions.behavior = _Resp(_MS("member-A", "org-X", ["stytch_admin"]))
    out = run(TOK, h.A)
    check(
        "reverify: success -> fresh Principal",
        isinstance(out, auth.Principal) and out.user_id == "member-A",
    )
    sent = fake.sessions.calls[-1]
    check(
        "reverify: sends the opaque session_token (not the JWT)",
        sent.get("session_token") == "sess-abc" and "session_jwt" not in sent,
    )
    ac = sent.get("authorization_check")
    check(
        "reverify: carries AuthorizationCheck(org_skills/manage) for the caller's org",
        ac is not None
        and ac.organization_id == "org-X"
        and ac.resource_id == "org_skills"
        and ac.action == "manage",
    )

    check("reverify: missing X-Session-Token -> 401", run({}, h.A) == 401)
    fake.sessions.behavior = StytchError(StytchErrorDetails.from_unknown(403))
    check("reverify: Stytch 403 (RBAC denied) -> 403", run(TOK, h.A) == 403)
    fake.sessions.behavior = StytchError(StytchErrorDetails.from_unknown(401))
    check("reverify: Stytch 401 (revoked) -> 401", run(TOK, h.A) == 401)
    fake.sessions.behavior = RuntimeError("network down")
    check("reverify: transport error -> 401 (fail closed)", run(TOK, h.A) == 401)
    fake.sessions.behavior = _Resp(_MS("member-B", "org-X", ["stytch_admin"]))
    check("reverify: session token belongs to someone else -> 401", run(TOK, h.A) == 401)

    finish()


if __name__ == "__main__":
    test_admin_gate()

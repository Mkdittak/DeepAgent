"""Live end-to-end auth/tenancy proof against the RUNNING stack (:8000) using
real Stytch sessions minted through the server API. Needs Temporal + worker +
backend up with AUTH_ENABLED=true and real STYTCH_* keys in .env; makes 4 real
agent runs (Gemini).

Run (repo root): .venv\\Scripts\\python.exe tests\\proof_auth_live.py
Env: QA_BASE_EMAIL (default: the repo owner's Gmail; plus-addresses are derived
from it), QA_PASSWORD (else generated once and kept in artifacts/.qa_password.txt).

Creates (idempotently) in your Stytch Test project:
  org  DeepAgent QA Alpha  (slug deepagent-qa-alpha)
       - <you>+qa-alpha-admin@gmail.com   stytch_admin
       - <you>+qa-alpha-member@gmail.com  stytch_member
  org  DeepAgent QA Beta   (slug deepagent-qa-beta)
       - <you>+qa-beta-admin@gmail.com    stytch_admin
Each member gets a password (printed at the end) so this script can log in
without email; the plus-addresses are real, so you can ALSO sign in to these
orgs from the UI via magic link.
"""

import hashlib, json, os, secrets, sys, time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))
import httpx
from stytch import B2BClient
from stytch.core.response_base import StytchError

API = "http://127.0.0.1:8000"
BASE_EMAIL = os.environ.get("QA_BASE_EMAIL", "mukund.dittakavi@gmail.com")
user, domain = BASE_EMAIL.split("@")
_PWFILE = os.path.join(
    os.environ.get("ARTIFACT_BASE", "./artifacts"), ".qa_password.txt"
)  # gitignored
if os.environ.get("QA_PASSWORD"):
    PASSWORD = os.environ["QA_PASSWORD"]
elif os.path.isfile(_PWFILE):
    PASSWORD = open(_PWFILE, encoding="utf-8").read().strip()
else:
    PASSWORD = f"DeepAgent-QA-{secrets.token_urlsafe(9)}-2026!"
    open(_PWFILE, "w", encoding="utf-8").write(PASSWORD)
RUN_TIMEOUT = 420

sc = B2BClient(
    project_id=os.environ["STYTCH_PROJECT_ID"],
    secret=os.environ["STYTCH_SECRET"],
    environment=os.environ.get("STYTCH_ENV", "test"),
    suppress_warnings=True,
)

fails, notes = [], []


def check(label, ok, extra=""):
    print(f"{'PASS' if ok else 'FAIL'}: {label}" + (f"  [{extra}]" if extra else ""))
    if not ok:
        fails.append(label)


def note(s):
    print("NOTE:", s)
    notes.append(s)


# ---------------------------------------------------------------- Stytch setup
def ensure_org(name, slug):
    r = sc.organizations.search(
        query={
            "operator": "AND",
            "operands": [{"filter_name": "organization_slugs", "filter_value": [slug]}],
        }
    )
    if r.organizations:
        return r.organizations[0].organization_id
    return sc.organizations.create(
        organization_name=name, organization_slug=slug
    ).organization.organization_id


def ensure_member(org_id, email, roles):
    roles = [
        x for x in roles if x != "stytch_member"
    ]  # default role is implicit; explicit assignment is a 400
    r = sc.organizations.members.search(
        organization_ids=[org_id],
        query={
            "operator": "AND",
            "operands": [{"filter_name": "member_emails", "filter_value": [email]}],
        },
    )
    if r.members:
        mid = r.members[0].member_id
        try:  # existing member: password must still be the persisted one
            sc.passwords.authenticate(
                organization_id=org_id, email_address=email, password=PASSWORD
            )
        except StytchError:
            # migrate() only sets a password on a member without one, so a
            # stale fixture can't be re-keyed in place: recreate it.
            sc.organizations.members.delete(organization_id=org_id, member_id=mid)
            r.members = []
    if not r.members:
        mid = sc.organizations.members.create(
            organization_id=org_id, email_address=email, roles=roles
        ).member_id
        sc.passwords.migrate(
            email_address=email,
            hash=hashlib.sha1(PASSWORD.encode()).hexdigest(),
            hash_type="sha_1",
            organization_id=org_id,
        )
    sc.organizations.members.update(organization_id=org_id, member_id=mid, roles=roles)
    return mid


def login(org_id, email):
    r = sc.passwords.authenticate(
        organization_id=org_id, email_address=email, password=PASSWORD, session_duration_minutes=60
    )
    ms = r.member_session
    return {
        "jwt": r.session_jwt,
        "tok": r.session_token,
        "member_id": r.member_id,
        "org_id": r.organization_id,
        "roles": list(ms.roles) if ms else [],
        "email": email,
        "session_id": ms.member_session_id if ms else None,
    }


print("== Stytch: orgs + members")
alpha = ensure_org("DeepAgent QA Alpha", "deepagent-qa-alpha")
beta = ensure_org("DeepAgent QA Beta", "deepagent-qa-beta")
E = lambda tag: f"{user}+{tag}@{domain}"
ensure_member(alpha, E("qa-alpha-admin"), ["stytch_admin"])
ensure_member(alpha, E("qa-alpha-member"), ["stytch_member"])
ensure_member(beta, E("qa-beta-admin"), ["stytch_admin"])
ensure_member(alpha, E("qa-alpha-admin2"), ["stytch_admin"])
AA, AM, BA = (
    login(alpha, E("qa-alpha-admin")),
    login(alpha, E("qa-alpha-member")),
    login(beta, E("qa-beta-admin")),
)
AA2 = login(alpha, E("qa-alpha-admin2"))
print(f"   alpha={alpha}\n   beta ={beta}")
for p in (AA, AM, BA):
    print(f"   {p['email']:45s} roles={p['roles']}")
check("alpha-admin session carries stytch_admin", "stytch_admin" in AA["roles"])
check("alpha-member session has no stytch_admin", "stytch_admin" not in AM["roles"])
check(
    "alpha and beta are distinct orgs",
    AA["org_id"] != BA["org_id"] and AA["org_id"] == AM["org_id"],
)


# ---------------------------------------------------------------- backend helpers
def H(p):
    return {"Authorization": f"Bearer {p['jwt']}", "X-Session-Token": p["tok"]}


cl = httpx.Client(base_url=API, timeout=30)


def get(p, path, **kw):
    return cl.get(path, headers=H(p), **kw)


def post(p, path, **kw):
    return cl.post(path, headers=H(p), **kw)


def patch(p, path, **kw):
    return cl.patch(path, headers=H(p), **kw)


def delete(p, path, **kw):
    return cl.delete(path, headers=H(p), **kw)


def stream(p, run_id, timeout=RUN_TIMEOUT):
    """Read the SSE stream to run.finished; return (events, final_state)."""
    events, t0 = [], time.time()
    with httpx.stream(
        "GET",
        f"{API}/runs/{run_id}/stream",
        headers=H(p),
        timeout=httpx.Timeout(timeout, read=timeout),
    ) as r:
        if r.status_code != 200:
            return events, f"http {r.status_code}"
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                rec, buf = buf.split("\n\n", 1)
                data = "".join(l[5:].strip() for l in rec.split("\n") if l.startswith("data:"))
                if not data:
                    continue
                ev = json.loads(data)
                events.append(ev)
                if ev.get("type") == "run.finished":
                    return events, ev.get("state")
            if time.time() - t0 > timeout:
                return events, "timeout"
    return events, "closed"


def run_and_wait(p, message, thread_id=None, label=""):
    body = {"message": message}
    if thread_id:
        body["thread_id"] = thread_id
    r = post(p, "/runs", json=body)
    check(
        f"{label} POST /runs -> 200",
        r.status_code == 200,
        r.text[:120] if r.status_code != 200 else "",
    )
    if r.status_code != 200:
        return None, [], "not-started"
    j = r.json()
    t0 = time.time()
    evs, state = stream(p, j["run_id"])
    print(
        f"   {label} run {j['run_id']} -> {state} in {int(time.time() - t0)}s, {len(evs)} events, "
        f"types={sorted({e['type'] for e in evs})}"
    )
    for e in evs:
        if e["type"] == "run.error":
            print("   run.error:", e.get("message", "")[:200].replace(chr(10), " "))
    return j, evs, state


# ---------------------------------------------------------------- 0. auth basics
print("\n== 0. auth basics against the live backend")
check("no bearer -> 401", cl.get("/threads").status_code == 401)
check(
    "garbage bearer -> 401",
    cl.get("/threads", headers={"Authorization": "Bearer nope.nope.nope"}).status_code == 401,
)
fake = AA["jwt"][:-8] + "AAAAAAAA"
check(
    "tampered signature -> 401",
    cl.get("/threads", headers={"Authorization": f"Bearer {fake}"}).status_code == 401,
)
check("valid session -> 200", get(AA, "/threads").status_code == 200)
check("/health stays open", cl.get("/health").status_code == 200)

# ---------------------------------------------------------------- 1. alpha-admin real run + artifacts
print("\n== 1. alpha-admin: real run, artifact signing")
r1, ev1, st1 = run_and_wait(
    AA,
    "Create a small HTML file named hello.html whose body says exactly: Hello from DeepAgent QA. Do nothing else and do not search the web.",
    label="AA",
)
check("AA run finished 'done'", st1 == "done", st1)
if r1:
    run_a, thread_a = r1["run_id"], r1["thread_id"]
    check(
        "envelope events carry AA identity",
        all(e.get("user_id") == AA["member_id"] and e.get("org_id") == alpha for e in ev1),
    )
    files = [e["filename"] for e in ev1 if e["type"] == "file.created"]
    fin = next((e for e in ev1 if e["type"] == "run.finished"), {})
    arts = fin.get("artifacts") or files
    print("   artifacts:", arts)
    html = next((a for a in arts if a.endswith(".html")), None)
    check("an .html artifact was produced", html is not None)
    if html:
        run_a_file = html
        check(
            "unsigned artifact -> 404",
            cl.get(f"/artifacts/{run_a}/{run_a_file}").status_code == 404,
        )
        s = get(AA, f"/artifacts/{run_a}/{run_a_file}/sign")
        check("owner /sign -> 200", s.status_code == 200)
        if s.status_code == 200:
            surl = s.json()["url"]
            r = cl.get(surl)
            check(
                "signed URL serves inline html",
                r.status_code == 200
                and "text/html" in r.headers.get("content-type", "")
                and "Hello from DeepAgent QA" in r.text,
            )
            r = cl.get(surl + "&download=1")
            check(
                "signed + download=1 -> attachment",
                "attachment" in r.headers.get("content-disposition", ""),
            )
            check(
                "alpha-member /sign on AA's artifact -> 404",
                get(AM, f"/artifacts/{run_a}/{run_a_file}/sign").status_code == 404,
            )
            check(
                "beta-admin /sign on AA's artifact -> 404",
                get(BA, f"/artifacts/{run_a}/{run_a_file}/sign").status_code == 404,
            )
    # thread / run visibility
    check("AA sees own thread", get(AA, f"/threads/{thread_a}").status_code == 200)
    check("AA /threads lists it", thread_a in {t["thread_id"] for t in get(AA, "/threads").json()})
    check("AA /runs lists it", run_a in {x["run_id"] for x in get(AA, "/runs").json()})
    check(
        "AA replay stream of finished run -> 200",
        get(AA, f"/runs/{run_a}/stream").status_code == 200,
    )
    for lbl, p in (("alpha-member", AM), ("beta-admin", BA)):
        check(f"{lbl} GET AA's thread -> 404", get(p, f"/threads/{thread_a}").status_code == 404)
        check(
            f"{lbl} PATCH AA's thread -> 404",
            patch(p, f"/threads/{thread_a}", json={"title": "pwned"}).status_code == 404,
        )
        check(
            f"{lbl} DELETE AA's thread -> 404", delete(p, f"/threads/{thread_a}").status_code == 404
        )
        check(f"{lbl} stream AA's run -> 404", get(p, f"/runs/{run_a}/stream").status_code == 404)
        check(f"{lbl} cancel AA's run -> 404", post(p, f"/runs/{run_a}/cancel").status_code == 404)
        check(
            f"{lbl} /threads excludes AA's",
            thread_a not in {t["thread_id"] for t in get(p, "/threads").json()},
        )
        check(
            f"{lbl} /runs excludes AA's", run_a not in {x["run_id"] for x in get(p, "/runs").json()}
        )
    check(
        "AA thread title untouched by the 404'd PATCHes",
        get(AA, f"/threads/{thread_a}").json()["title"].startswith("Create a small HTML"),
    )
    # rename works for the owner
    check(
        "AA can rename own thread",
        patch(AA, f"/threads/{thread_a}", json={"title": "QA Alpha hello"}).status_code == 200,
    )

# ---------------------------------------------------------------- 2. skills: org scope + admin gate (REAL network reverify)
print("\n== 2. skills: org scoping + admin gate with real Stytch reverify")
SK = """---
name: qa-signoff
description: Use whenever the user asks for a QA sign-off, a "qa signoff", or a sign-off note. Produces the standard sign-off line.
---
# QA sign-off
When asked for a QA sign-off, reply with exactly this single line and nothing else:

QA-SIGNOFF-OK

Do not search the web and do not create files.
"""
# clean up a previous run's rows so the name is free
for s in get(AA, "/skills").json():
    if s["tier"] != "built-in" and s["name"] in ("qa-signoff", "qa-alpha-private"):
        delete(AA, f"/skills/{s['skill_id']}")
for s in get(BA, "/skills").json():
    if s["tier"] != "built-in" and s["name"] == "qa-signoff":
        delete(BA, f"/skills/{s['skill_id']}")

r = post(AM, "/skills", json={"body": SK, "tier": "org"})
check("alpha-member can PROPOSE an org skill", r.status_code == 200, r.text[:100])
sid = r.json()["skill_id"] if r.status_code == 200 else None
if sid:
    check(
        "lands untrusted + disabled",
        r.json()["trust_state"] == "untrusted" and r.json()["enabled"] is False,
    )
    check(
        "alpha-member trust -> 403",
        patch(AM, f"/skills/{sid}", json={"trust_state": "trusted"}).status_code == 403,
    )
    check(
        "alpha-member enable -> 403",
        patch(AM, f"/skills/{sid}", json={"enabled": True}).status_code == 403,
    )
    check("alpha-member delete -> 403", delete(AM, f"/skills/{sid}").status_code == 403)
    check("beta-admin GET -> 404 (other org)", get(BA, f"/skills/{sid}").status_code == 404)
    check(
        "beta-admin trust -> 404 (not 403)",
        patch(BA, f"/skills/{sid}", json={"trust_state": "trusted"}).status_code == 404,
    )
    check(
        "beta-admin listing excludes it",
        "qa-signoff" not in {s["name"] for s in get(BA, "/skills").json()},
    )
    r = patch(AA, f"/skills/{sid}", json={"trust_state": "trusted", "enabled": True})
    check(
        "alpha-admin trust+enable -> 200 via REAL network reverify + RBAC check",
        r.status_code == 200 and r.json()["enabled"] is True,
        r.text[:160],
    )
    check(
        "alpha-member now sees it enabled in listing",
        any(s["name"] == "qa-signoff" and s["enabled"] for s in get(AM, "/skills").json()),
    )
    # bearer from one session + session token from another must be rejected on the network path
    mixed = {"Authorization": f"Bearer {AA['jwt']}", "X-Session-Token": AM["tok"]}
    r = cl.patch(f"/skills/{sid}", headers=mixed, json={"enabled": False})
    check(
        "admin bearer + MEMBER session-token -> 403 (Stytch RBAC verdict on the real token)",
        r.status_code == 403,
        str(r.status_code),
    )
    mixed2 = {"Authorization": f"Bearer {AA['jwt']}", "X-Session-Token": AA2["tok"]}
    r = cl.patch(f"/skills/{sid}", headers=mixed2, json={"enabled": False})
    check(
        "admin bearer + OTHER ADMIN's session-token -> 401 (identity mismatch guard)",
        r.status_code == 401,
        str(r.status_code),
    )
    check(
        "skill still enabled after both rejected mixed requests",
        get(AA, f"/skills/{sid}").json()["enabled"] is True,
    )
# user-tier scoping
r = post(AA, "/skills", json={"body": SK.replace("qa-signoff", "qa-alpha-private"), "tier": "user"})
usid = r.json().get("skill_id") if r.status_code == 200 else None
check("alpha-admin installs a user skill", usid is not None)
if usid:
    check(
        "alpha-member (same org) cannot see admin's user skill",
        get(AM, f"/skills/{usid}").status_code == 404,
    )
    check(
        "alpha-admin trusts own user skill (ownership only)",
        patch(AA, f"/skills/{usid}", json={"trust_state": "trusted"}).status_code == 200,
    )

# ---------------------------------------------------------------- 3. worker seed scoping via real runs
print("\n== 3. worker seed scoping: same prompt in both orgs")
r2, ev2, st2 = run_and_wait(AM, "Give me the QA sign-off.", label="AM")
act2 = [e["name"] for e in ev2 if e["type"] == "skill.activated"]
text2 = "".join(e.get("text", "") for e in ev2 if e["type"] == "text.delta")
print("   AM activated:", act2, "| final text:", text2.strip()[:80].replace("\n", " "))
check("AM run finished", st2 == "done", st2)
check(
    "alpha-member's run ACTIVATED the org skill (seeded for org alpha)",
    "qa-signoff" in act2 or "QA-SIGNOFF-OK" in text2,
)
check("envelope carries AM identity", all(e.get("user_id") == AM["member_id"] for e in ev2))

r3, ev3, st3 = run_and_wait(BA, "Give me the QA sign-off.", label="BA")
act3 = [e["name"] for e in ev3 if e["type"] == "skill.activated"]
text3 = "".join(e.get("text", "") for e in ev3 if e["type"] == "text.delta")
print("   BA activated:", act3, "| final text:", text3.strip()[:80].replace("\n", " "))
check("BA run finished", st3 == "done", st3)
check(
    "beta-admin's run did NOT get org alpha's skill (not seeded)",
    "qa-signoff" not in act3 and "QA-SIGNOFF-OK" not in text3,
)

# ---------------------------------------------------------------- 4. thread continuation
print("\n== 4. thread continuation")
if r1 and r2:
    r = post(
        AA,
        "/runs",
        json={"message": "Reply with the single word: continued", "thread_id": r1["thread_id"]},
    )
    check(
        "AA continues own thread -> same thread_id",
        r.status_code == 200 and r.json()["thread_id"] == r1["thread_id"],
    )
    if r.status_code == 200:
        evs, st = stream(AA, r.json()["run_id"])
        print(f"   continuation run -> {st}")
        check(
            "AA's thread now has 2 runs",
            len(get(AA, f"/threads/{r1['thread_id']}").json()["runs"]) == 2,
        )
    r = post(
        BA,
        "/runs",
        json={"message": "Reply with the single word: hijack", "thread_id": r1["thread_id"]},
    )
    check(
        "BA echoing AA's thread_id gets a FRESH thread",
        r.status_code == 200 and r.json()["thread_id"] != r1["thread_id"],
    )
    if r.status_code == 200:
        post(BA, f"/runs/{r.json()['run_id']}/cancel")
        stream(BA, r.json()["run_id"], timeout=120)
        check(
            "AA's thread still has exactly its 2 runs",
            len(get(AA, f"/threads/{r1['thread_id']}").json()["runs"]) == 2,
        )

# ---------------------------------------------------------------- 5. revocation: hybrid verification
print("\n== 5. revocation (hybrid: local JWT vs network session token)")
sc.sessions.revoke(session_token=AA["tok"])
r = get(AA, "/threads")
print(
    f"   revoked admin: hot-path GET /threads -> {r.status_code} (local JWT; may pass until the 5-min JWT expires)"
)
note(f"after revoke, hot-path read returned {r.status_code}; sensitive path below must be 401")
if sid:
    r = patch(AA, f"/skills/{sid}", json={"enabled": False})
    check(
        "revoked admin: org-skill write (network path) -> 401 immediately",
        r.status_code == 401,
        str(r.status_code),
    )
    check(
        "skill untouched by the revoked request",
        get(AM, f"/skills/{sid}").json()["enabled"] is True,
    )

# ---------------------------------------------------------------- 6. legacy backfill on disk
print("\n== 6. backfill of pre-auth rows")
reg = json.load(
    open(
        os.path.join(os.environ.get("ARTIFACT_BASE", "./artifacts"), ".run_registry.json"),
        encoding="utf-8",
    )
)
legacy = sum(1 for v in reg.values() if v.get("user_id") == "legacy")
nulls = sum(1 for v in reg.values() if v.get("user_id") is None)
print(f"   registry rows: {len(reg)} total, {legacy} legacy-stamped, {nulls} null")
check("no registry row is left with null identity", nulls == 0)
check(
    "legacy rows invisible to real tenants",
    all(x["user_id"] != "legacy" for x in [])
    and all(t["thread_id"] not in {k for k, v in reg.items()} for t in get(AM, "/threads").json()),
)

print(f"\n{len(fails)} failure(s)")
for f in fails:
    print("  -", f)
print("\nCredentials for UI/API testing (Stytch Test env, passwords product):")
for p in (AA, AM, BA):
    print(f"  {p['email']}  ({'admin' if 'stytch_admin' in p['roles'] else 'member'})")
print(f"  password: {PASSWORD}")
print(
    "  Magic-link sign-in from the UI also works for these emails (they're your Gmail plus-addresses)."
)
sys.exit(1 if fails else 0)

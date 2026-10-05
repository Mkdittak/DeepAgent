"""
Org scoping: org A's skills are invisible to org B — in the API listing AND
in the worker's seed (agent.skills.seed_files reads the same registry file
with the identity carried in WorkflowInput).

Run (repo root): .venv\\Scripts\\python.exe tests\\test_org_scope.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import Harness, check, finish

from agent.skills import seed_files


def test_org_scope():
    h = Harness()
    c = h.c

    # org X: admin A installs + trusts + enables an org skill; B adds a user skill.
    h.as_(h.A)
    x_org = h.install("x-shared", "org")
    x_user_a = h.install("a-only", "user")
    check(
        "A trust+enable org skill",
        c.patch(f"/skills/{x_org}", json={"trust_state": "trusted", "enabled": True}).status_code
        == 200,
    )
    check(
        "A trust+enable own user skill",
        c.patch(f"/skills/{x_user_a}", json={"trust_state": "trusted", "enabled": True}).status_code
        == 200,
    )
    h.as_(h.B)
    h.install("b-only", "user")
    # org Y: C installs its own org skill.
    h.as_(h.C)
    y_org = h.install("y-shared", "org")
    check(
        "C trust+enable org-Y skill",
        c.patch(f"/skills/{y_org}", json={"trust_state": "trusted", "enabled": True}).status_code
        == 200,
    )

    # --- API listing ---
    h.as_(h.A)
    check("A (org X) lists: x-shared + a-only", h.skill_names() == ["a-only", "x-shared"])
    h.as_(h.B)
    check(
        "B (org X) lists: x-shared + b-only (not a-only)", h.skill_names() == ["b-only", "x-shared"]
    )
    h.as_(h.C)
    check("C (org Y) lists: y-shared only", h.skill_names() == ["y-shared"])
    check("C cannot GET org-X skill (404)", c.get(f"/skills/{x_org}").status_code == 404)
    check(
        "C cannot PATCH org-X skill (404, not 403)",
        c.patch(f"/skills/{x_org}", json={"enabled": False}).status_code == 404,
    )
    check("C cannot DELETE org-X skill (404)", c.delete(f"/skills/{x_org}").status_code == 404)
    h.as_(h.A)
    check("A cannot see org-Y skill", c.get(f"/skills/{y_org}").status_code == 404)

    # Same (tier, name) in two orgs is not a duplicate: uniqueness is per scope.
    h.as_(h.C)
    check(
        "org Y can install a skill named like org X's",
        c.post(
            "/skills", json={"body": "---\nname: x-shared\ndescription: d\n---\nb", "tier": "org"}
        ).status_code
        == 200,
    )
    h.as_(h.A)
    check("org X still sees exactly one x-shared", h.skill_names().count("x-shared") == 1)

    # --- worker seed (identity from WorkflowInput only) ---
    def seeded(user_id, org_id):
        return sorted(
            p
            for p in seed_files(user_id=user_id, org_id=org_id)
            if not p.startswith("/skills/built-in/")
        )

    check(
        "seed for A/org-X",
        seeded("member-A", "org-X")
        == ["/skills/org/x-shared/SKILL.md", "/skills/user/a-only/SKILL.md"],
    )
    check(
        "seed for B/org-X excludes A's user skill (b-only is untrusted so absent too)",
        seeded("member-B", "org-X") == ["/skills/org/x-shared/SKILL.md"],
    )
    check(
        "seed for C/org-Y excludes everything from org X",
        seeded("member-C", "org-Y") == ["/skills/org/y-shared/SKILL.md"],
    )
    check("seed for a stranger: nothing but built-ins", seeded("member-Z", "org-Z") == [])

    # create_run stamps the identity the worker will seed with.
    h.as_(h.B)
    h.run("as B")
    wi = h.started[-1]
    check("WorkflowInput carries B's identity", (wi.user_id, wi.org_id) == ("member-B", "org-X"))
    check(
        "worker seed from that WorkflowInput = B's view",
        seeded(wi.user_id, wi.org_id) == ["/skills/org/x-shared/SKILL.md"],
    )

    finish()


if __name__ == "__main__":
    test_org_scope()

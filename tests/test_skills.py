"""
Slice-1 checks for the Agent Skills integration (agentskills.io).

Run: python tests/test_skills.py
Verifies: shipped built-in skills conform to the SKILL.md spec, the seed
builder produces the flat one-level layout SkillsMiddleware discovery needs,
scripts/ never reach agent state, and the custom prompt template satisfies
SkillsMiddleware's placeholder validation.
"""

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

import agent.skills as skills_mod
from agent.skills import BUILTIN_SKILLS_DIR, SKILLS_SYSTEM_PROMPT, builtin_seed_files

# Spec: 1-64 chars, lowercase a-z0-9 + hyphens, no leading/trailing/consecutive hyphens.
NAME_RE = re.compile(r"^(?!-)(?!.*--)[a-z0-9-]{1,64}(?<!-)$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

failures = []


def check(label: str, ok: bool):
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    if not ok:
        failures.append(label)


# --- 1. Shipped built-in skills conform to the agentskills.io spec ---------
skill_dirs = [d for d in sorted(BUILTIN_SKILLS_DIR.iterdir()) if d.is_dir()]
check("at least one built-in skill ships", len(skill_dirs) >= 1)

for d in skill_dirs:
    md = d / "SKILL.md"
    check(f"{d.name}: SKILL.md exists", md.is_file())
    if not md.is_file():
        continue
    text = md.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    check(f"{d.name}: frontmatter present", m is not None)
    if not m:
        continue
    fm = yaml.safe_load(m.group(1))
    name = fm.get("name", "")
    desc = fm.get("description", "")
    check(f"{d.name}: name matches spec charset/length", bool(NAME_RE.match(name)))
    check(f"{d.name}: name matches parent directory", name == d.name)
    check(f"{d.name}: description 1-1024 chars", 1 <= len(desc) <= 1024)
    if "compatibility" in fm:
        check(f"{d.name}: compatibility <= 500 chars", len(fm["compatibility"]) <= 500)
    body_lines = text[m.end() :].count("\n")
    check(f"{d.name}: SKILL.md under 500 lines", body_lines < 500)

# --- 2. Seed builder: flat layout, one level deep at the source root -------
seed = builtin_seed_files()
check("seed is non-empty", len(seed) > 0)
for d in skill_dirs:
    check(
        f"{d.name}: seeded at /skills/built-in/{d.name}/SKILL.md",
        f"/skills/built-in/{d.name}/SKILL.md" in seed,
    )
check(
    "all seed paths under /skills/built-in/", all(p.startswith("/skills/built-in/") for p in seed)
)
check("no scripts/ content in seed", not any("/scripts/" in p for p in seed))

# --- 3. scripts/ exclusion holds even when a scripts dir exists ------------
with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp) / "built-in" / "demo-skill"
    (fake / "scripts").mkdir(parents=True)
    (fake / "references").mkdir()
    (fake / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    (fake / "scripts" / "run.py").write_text("print('no')\n", encoding="utf-8")
    (fake / "references" / "ref.md").write_text("ref\n", encoding="utf-8")
    orig = skills_mod.BUILTIN_SKILLS_DIR
    skills_mod.BUILTIN_SKILLS_DIR = Path(tmp) / "built-in"
    try:
        tmp_seed = builtin_seed_files()
    finally:
        skills_mod.BUILTIN_SKILLS_DIR = orig
    check("temp tree: SKILL.md seeded", "/skills/built-in/demo-skill/SKILL.md" in tmp_seed)
    check(
        "temp tree: references/ seeded", "/skills/built-in/demo-skill/references/ref.md" in tmp_seed
    )
    check("temp tree: scripts/ excluded", not any("scripts" in p for p in tmp_seed))

# --- 4. Custom template passes SkillsMiddleware placeholder validation -----
from deepagents.backends import StateBackend
from deepagents.middleware import SkillsMiddleware

try:
    SkillsMiddleware(
        backend=StateBackend(),
        sources=[("/skills/built-in", "Built-in")],
        system_prompt=SKILLS_SYSTEM_PROMPT,
    )
    check("SkillsMiddleware accepts custom instruction-only template", True)
except (ValueError, TypeError) as e:
    check(f"SkillsMiddleware accepts custom instruction-only template ({e})", False)

check(
    "template contains no execute-scripts guidance",
    "Executing Skill Scripts" not in SKILLS_SYSTEM_PROMPT,
)

# --- 5. Store seam + seeding trust gate (slice 3) --------------------------
import backend.store as store
from agent.skills import builtin_skill_records, parse_skill_md, seed_files

with tempfile.TemporaryDirectory() as tmp:
    reg_file = str(Path(tmp) / ".skill_registry.json")
    orig_state = (
        store.SKILLS_FILE,
        store.ARTIFACT_BASE,
        dict(store._skills),
        store._skills_loaded,
        skills_mod.SKILL_REGISTRY_FILE,
    )
    store.SKILLS_FILE = reg_file
    store.ARTIFACT_BASE = tmp
    store._skills = {}
    store._skills_loaded = True
    skills_mod.SKILL_REGISTRY_FILE = reg_file
    try:
        builtins = builtin_skill_records()
        check("builtin records found", len(builtins) >= 2)
        check(
            "builtin ids deterministic",
            all(b["skill_id"] == f"builtin-{b['name']}" for b in builtins),
        )

        # Spec enforcement at install time
        _, err = parse_skill_md("no frontmatter here")
        check("parse rejects missing frontmatter", err is not None)
        _, err = parse_skill_md("---\nname: Bad--Name\ndescription: d\n---\nx")
        check("parse rejects invalid name", err is not None)
        meta, err = parse_skill_md(
            "---\nname: good-skill\ndescription: does things. use for tests.\n---\nBody."
        )
        check("parse accepts valid SKILL.md", err is None and meta["name"] == "good-skill")

        # Install lands untrusted + disabled
        row = store.install_skill(
            "good-skill",
            "user",
            meta["description"],
            "upload",
            "---\nname: good-skill\ndescription: d\n---\nBody.",
            {"references/r.md": "ref", "scripts/x.py": "print(1)"},
        )
        check("install returns row", row is not None)
        check("install lands untrusted", row["trust_state"] == "untrusted")
        check("install lands disabled", row["enabled"] is False)
        check(
            "duplicate (tier,name) rejected",
            store.install_skill("good-skill", "user", "d", "upload", "b", {}) is None,
        )

        # THE invariant: untrusted-or-disabled rows never reach agent state
        seed = seed_files()
        check(
            "untrusted skill absent from seed",
            not any("/skills/user/good-skill/" in p for p in seed),
        )
        sid = row["skill_id"]
        store.set_skill_trust(sid, "trusted")
        seed = seed_files()
        check(
            "trusted-but-disabled still absent from seed", not any("good-skill" in p for p in seed)
        )
        store.set_skill_enabled(sid, True, builtins)
        seed = seed_files()
        check("trusted+enabled seeds SKILL.md", "/skills/user/good-skill/SKILL.md" in seed)
        check(
            "references seed for registry skills", "/skills/user/good-skill/references/r.md" in seed
        )
        check("scripts never seed for registry skills", not any("/scripts/" in p for p in seed))

        # Revoking trust disables seeding again; soft delete removes entirely
        store.set_skill_trust(sid, "untrusted")
        check("revoked skill absent from seed", not any("good-skill" in p for p in seed_files()))
        check("soft delete works", store.soft_delete_skill(sid) is True)
        check(
            "built-in delete refused by store",
            store.soft_delete_skill(builtins[0]["skill_id"]) is False,
        )

        # Built-in disable override flows through to the seed
        b0 = builtins[0]
        store.set_skill_enabled(b0["skill_id"], False, builtins)
        check(
            "disabled built-in absent from seed",
            not any(f"/skills/built-in/{b0['name']}/" in p for p in seed_files()),
        )
        store.set_skill_enabled(b0["skill_id"], True, builtins)
        check(
            "re-enabled built-in back in seed",
            f"/skills/built-in/{b0['name']}/SKILL.md" in seed_files(),
        )

        # Listing merges tiers; registry file survives on disk
        listed = store.list_skills(builtins)
        check(
            "list includes built-ins",
            sum(1 for s in listed if s["tier"] == "built-in") == len(builtins),
        )
        check("list hides deleted user skill", not any(s["skill_id"] == sid for s in listed))
        check("registry file persisted", Path(reg_file).is_file())
    finally:
        (
            store.SKILLS_FILE,
            store.ARTIFACT_BASE,
            store._skills,
            store._skills_loaded,
            skills_mod.SKILL_REGISTRY_FILE,
        ) = (orig_state[0], orig_state[1], orig_state[2], orig_state[3], orig_state[4])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)

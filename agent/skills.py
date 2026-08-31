"""
Agent Skills (agentskills.io) wiring — v1: built-in tier, instruction-only.

Skills are folders with a SKILL.md (YAML frontmatter: name + description),
loaded by deepagents' native SkillsMiddleware via progressive disclosure:
name+description injected into the system prompt every call, full SKILL.md
read on demand with read_file, bundled references/ read as needed.

Storage: built-in skills ship on disk in the repo `skills/built-in/`
directory (trust = git + code review). The agent's filesystem is the virtual
StateBackend, so before each run the worker seeds every built-in skill file
into the LangGraph `files` state channel under /skills/built-in/... —
SkillsMiddleware then discovers them through backend.ls()/download_files()
with zero custom backend code. Org/user tiers arrive with the skill registry
(store seam); script execution is disabled until the auth + sandbox milestone.

SECURITY (instruction-only v1): scripts/ contents are deliberately NEVER
seeded into agent state, and the prompt template below tells the model that
execution is off. The `execute` tool also hard-errors on StateBackend, so
"exec off" holds at both the data layer and the tool layer.
"""

import json
import os
import re
from pathlib import Path

import yaml

# Repo directory holding built-in skills (one subdirectory per skill).
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "built-in"

# Org/user tier rows live in the skill registry (backend/store.py writes it;
# the worker reads it fresh each run, read-only and cross-process — B1 moves
# both sides onto Postgres).
SKILL_REGISTRY_FILE = os.path.join(
    os.environ.get("ARTIFACT_BASE", "./artifacts"), ".skill_registry.json"
)

# agentskills.io spec: 1-64 chars, lowercase a-z/0-9/hyphens, no leading,
# trailing, or consecutive hyphens.
SKILL_NAME_RE = re.compile(r"^(?!-)(?!.*--)[a-z0-9-]{1,64}(?<!-)$")
MAX_DESCRIPTION_LEN = 1024
MAX_COMPATIBILITY_LEN = 500

# Virtual-FS path prefix the agent sees. Order = priority (last wins on name
# collision) once org/user tiers are added after built-in.
BUILTIN_SOURCE = "/skills/built-in"

# Subdirectory whose contents must never reach agent state in v1 (exec off).
_EXCLUDED_SUBDIRS = {"scripts"}

# Skill bundle files are text (markdown, templates, data tables). Anything
# that fails UTF-8 decoding is skipped rather than corrupted.
_TEXT_ENCODING = "utf-8"


def builtin_seed_files() -> dict[str, str]:
    """Build the {virtual_path: content} seed for the invoke `files` input.

    Includes each built-in skill's SKILL.md plus references/ and assets/
    files; excludes scripts/ (instruction-only v1). Layout is kept exactly
    one level deep at the source root (/skills/built-in/<name>/SKILL.md)
    because SkillsMiddleware discovery does not recurse.
    """
    seed: dict[str, str] = {}
    if not BUILTIN_SKILLS_DIR.is_dir():
        return seed
    for skill_dir in sorted(BUILTIN_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
            continue
        for root, dirs, files in os.walk(skill_dir):
            rel_root = Path(root).relative_to(skill_dir)
            if not rel_root.parts:
                dirs[:] = [d for d in dirs if d not in _EXCLUDED_SUBDIRS]
            for fname in sorted(files):
                fpath = Path(root) / fname
                try:
                    content = fpath.read_text(encoding=_TEXT_ENCODING)
                except (UnicodeDecodeError, OSError):
                    continue
                virtual = "/".join(
                    [BUILTIN_SOURCE, skill_dir.name, *rel_root.parts, fname]
                    if rel_root.parts
                    else [BUILTIN_SOURCE, skill_dir.name, fname]
                )
                seed[virtual] = content
    return seed


# A read_file on a path of this shape is a skill activation (progressive
# disclosure stage 2) — the worker turns it into a skill.activated event.
SKILL_MD_RE = re.compile(r"^/skills/([^/]+)/([^/]+)/SKILL\.md$")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def skill_index(seed: dict[str, str]) -> dict[str, dict]:
    """Map each seeded SKILL.md path to {name, tier, description}.

    Used by the worker to enrich skill.activated events without re-reading
    disk: the tier comes from the path, name/description from frontmatter
    (falling back to the directory name when frontmatter is malformed).
    """
    index: dict[str, dict] = {}
    for path, content in seed.items():
        m = SKILL_MD_RE.match(path)
        if not m:
            continue
        tier, dirname = m.group(1), m.group(2)
        name, description = dirname, ""
        fm = _FRONTMATTER_RE.match(content)
        if fm:
            try:
                data = yaml.safe_load(fm.group(1)) or {}
                name = str(data.get("name") or dirname)
                description = str(data.get("description") or "")
            except yaml.YAMLError:
                pass
        index[path] = {"name": name, "tier": tier, "description": description}
    return index


def parse_skill_md(body: str) -> tuple[dict | None, str | None]:
    """Parse and spec-validate a SKILL.md. Returns (meta, error).

    Enforces the agentskills.io rules deepagents only warns about — used at
    install time so invalid skills are rejected with a 422, never stored.
    """
    fm = _FRONTMATTER_RE.match(body)
    if not fm:
        return None, "SKILL.md must start with YAML frontmatter (--- ... ---)"
    try:
        data = yaml.safe_load(fm.group(1)) or {}
    except yaml.YAMLError as e:
        return None, f"invalid YAML frontmatter: {e}"
    if not isinstance(data, dict):
        return None, "frontmatter must be a YAML mapping"
    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        return None, ("name is required: 1-64 lowercase letters, digits, and "
                      "hyphens; no leading/trailing/consecutive hyphens")
    if not isinstance(description, str) or not 1 <= len(description) <= MAX_DESCRIPTION_LEN:
        return None, f"description is required: 1-{MAX_DESCRIPTION_LEN} characters"
    compatibility = data.get("compatibility")
    if compatibility is not None and (
        not isinstance(compatibility, str) or not 1 <= len(compatibility) <= MAX_COMPATIBILITY_LEN
    ):
        return None, f"compatibility must be 1-{MAX_COMPATIBILITY_LEN} characters"
    return {
        "name": name,
        "description": description,
        "license": data.get("license"),
        "compatibility": compatibility,
        "metadata": data.get("metadata"),
        "allowed_tools": data.get("allowed-tools"),
    }, None


def builtin_skill_records() -> list[dict]:
    """Disk-shipped built-in skills as registry-shaped rows for the API.

    skill_id is deterministic ("builtin-<name>") — built-ins are shared and
    public, so the opaque-id rule (AUDIT C3) doesn't apply; the stable id is
    what lets an enable/disable override row in the registry refer to them.
    `files` includes scripts/ so the UI can show them locked; the seed layer
    is what excludes scripts from agent state.
    """
    records: list[dict] = []
    if not BUILTIN_SKILLS_DIR.is_dir():
        return records
    for skill_dir in sorted(BUILTIN_SKILLS_DIR.iterdir()):
        md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not md.is_file():
            continue
        try:
            body = md.read_text(encoding=_TEXT_ENCODING)
        except (UnicodeDecodeError, OSError):
            continue
        meta, err = parse_skill_md(body)
        if err:
            continue
        files: dict[str, str] = {}
        for root, _dirs, fnames in os.walk(skill_dir):
            rel_root = Path(root).relative_to(skill_dir)
            for fname in sorted(fnames):
                if not rel_root.parts and fname == "SKILL.md":
                    continue
                try:
                    content = (Path(root) / fname).read_text(encoding=_TEXT_ENCODING)
                except (UnicodeDecodeError, OSError):
                    continue
                files["/".join([*rel_root.parts, fname])] = content
        records.append({
            "skill_id": f"builtin-{meta['name']}",
            "name": meta["name"],
            "tier": "built-in",
            "description": meta["description"],
            "source": "repo",
            "trust_state": "trusted",
            "enabled": True,
            "body": body,
            "files": files,
        })
    return records


def _registry_rows() -> dict[str, dict]:
    """Fresh read of the skill registry (worker side, read-only)."""
    try:
        with open(SKILL_REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def seed_files() -> dict[str, str]:
    """Full {virtual_path: content} seed across tiers for the invoke input.

    Built-ins from disk minus any registry disable-override, plus org/user
    registry rows that are BOTH enabled AND trusted — an untrusted skill is
    never seeded, not even its description (Phase S: exclusion, not framing).
    scripts/ and path-traversing file keys never reach agent state.
    """
    rows = _registry_rows()
    disabled_builtins = {
        r.get("name")
        for r in rows.values()
        if r.get("tier") == "built-in" and not r.get("enabled", True) and not r.get("deleted_at")
    }
    seed = {
        path: content
        for path, content in builtin_seed_files().items()
        if path.split("/")[3] not in disabled_builtins
    }
    for row in rows.values():
        if row.get("tier") not in ("org", "user") or row.get("deleted_at"):
            continue
        if not row.get("enabled") or row.get("trust_state") != "trusted":
            continue
        name = row.get("name", "")
        body = row.get("body", "")
        if not SKILL_NAME_RE.match(name) or not body:
            continue
        base = f"/skills/{row['tier']}/{name}"
        seed[f"{base}/SKILL.md"] = body
        for rel, content in (row.get("files") or {}).items():
            rel = str(rel).replace("\\", "/").strip("/")
            parts = rel.split("/")
            if not rel or ".." in parts or parts[0] in _EXCLUDED_SUBDIRS:
                continue
            if not isinstance(content, str):
                continue
            seed[f"{base}/{rel}"] = content
    return seed


# Instruction-only replacement for deepagents' SKILLS_SYSTEM_PROMPT: drops the
# script-execution guidance (execute is stubbed here) and the skill-authoring
# nudge, keeps the three required {placeholders} (SkillsMiddleware validates).
SKILLS_SYSTEM_PROMPT = """## Skills System

You have access to a skills library that provides specialized workflows and domain knowledge.

{skills_locations}{skills_load_warnings}

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

1. **Recognize when a skill applies**: check whether the user's task matches a skill's description.
2. **Read the skill's full instructions**: use `read_file` on the path shown in the skill list above. Pass `limit=1000` since the default of 100 lines is too small for most skill files.
3. **Follow the skill's instructions**: SKILL.md contains the step-by-step workflow and rules for the task.
4. **Read supporting files when the skill points to them**: files under the skill's `references/` or `assets/` directories are read with `read_file` on their absolute path.

Skills are instructions and reference material ONLY. Script execution is disabled in this environment: never attempt to run anything under a skill's `scripts/` directory and never use the `execute` tool on skill content.

If a skill matches the task, read it BEFORE starting the work — one tool call, and the result gets better and more consistent."""

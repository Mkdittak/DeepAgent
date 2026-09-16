"""Claim the pre-auth LEGACY bucket for a real Stytch member + organization.

When AUTH_ENABLED was first turned on, every pre-existing run/thread/skill row
was stamped user_id="legacy", org_id="legacy" (backend.auth backfill). That
keeps the data but shows it to nobody. This one-off moves it to a real owner.

    .venv\\Scripts\\python.exe -m backend.claim_legacy --org <organization_id> --member <member_id> [--unarchive]

Run it with the backend STOPPED: the API keeps the run registry in memory and
would overwrite this on its next save. --unarchive also clears the "archived
on first thread-registry load" flag (A3) so the old conversations show in
the sidebar. Storage stays the JSON files; this is a data move, not a schema
change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from backend import auth, store  # noqa: E402

ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")
REGISTRY_FILE = os.path.join(ARTIFACT_BASE, ".run_registry.json")


def _load_registry() -> dict:
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(reg: dict) -> None:
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, REGISTRY_FILE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", required=True, help="Stytch organization_id to own the data")
    ap.add_argument("--member", required=True, help="Stytch member_id (in that org) to own the data")
    ap.add_argument("--from-user", default=auth.LEGACY_USER_ID)
    ap.add_argument("--from-org", default=auth.LEGACY_ORG_ID)
    ap.add_argument("--unarchive", action="store_true", help="clear deleted_at on claimed threads")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    reg = _load_registry()
    store.load(reg)
    src = store.Identity(a.from_user, a.from_org)
    dst = store.Identity(a.member, a.org)
    if a.dry_run:
        n_runs = sum(1 for v in reg.values() if isinstance(v, dict) and v.get("user_id") == src.user_id and v.get("org_id") == src.org_id)
        n_thr = sum(1 for t in store._threads.values() if t.get("user_id") == src.user_id and t.get("org_id") == src.org_id)
        print(f"dry run: would move {n_runs} runs, {n_thr} threads from {src} to {dst}")
        return 0
    counts = store.claim_identity(reg, src, dst, unarchive=a.unarchive)
    if counts["runs"]:
        _save_registry(reg)
    print(f"claimed for member={a.member} org={a.org}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

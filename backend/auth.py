"""Identity resolution for the API (Stytch B2B), behind the AUTH_ENABLED flag.

Identity resolves ONCE per request, here, into a `Principal`. Routes take it
as a FastAPI dependency and scope every read/write on it; the worker receives
the same values through WorkflowInput and never re-derives them.

    AUTH_ENABLED=false (default)  -> every request is the fixed LEGACY principal.
                                     Behavior is byte-identical to pre-auth.
    AUTH_ENABLED=true             -> Phase 1 verifies the Stytch session
                                     (local JWT on hot paths, network-backed on
                                     sensitive routes) and maps member_session
                                     -> Principal.

SDK names and shapes are verified against the installed package in
docs/STYTCH_NOTES.md; do not rely on memory for them.

Tenancy here is row scoping in the JSON stores (backend/store.py seam). This
is dev/staging auth. Production row-level security (Postgres RLS) is a
separately tracked step and is deliberately NOT introduced here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def auth_enabled() -> bool:
    """Read the feature flag at call time so tests can flip it via env."""
    return os.environ.get("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Principal:
    """Who is calling. user_id = Stytch member_id, org_id = organization_id."""
    user_id: str
    org_id: str
    roles: list[str] = field(default_factory=list)

    def has_role(self, role: str) -> bool:
        return role in self.roles


# The single implicit user of the pre-auth app. With the flag off every
# request is this principal; with the flag on, the startup backfill (Phase 1)
# stamps pre-auth rows with these ids so old data lands in a claimable bucket
# instead of vanishing from every real tenant's view.
LEGACY_USER_ID = "legacy"
LEGACY_ORG_ID = "legacy"
LEGACY_PRINCIPAL = Principal(
    user_id=LEGACY_USER_ID, org_id=LEGACY_ORG_ID, roles=["stytch_admin"]
)


async def get_principal() -> Principal:
    """FastAPI dependency. Phase 0 stub: flag off -> LEGACY; flag on -> not yet
    implemented (Phase 1 fills in Stytch verification). Nothing calls this yet.
    """
    if not auth_enabled():
        return LEGACY_PRINCIPAL
    raise NotImplementedError("AUTH_ENABLED=true is wired in Phase 1")

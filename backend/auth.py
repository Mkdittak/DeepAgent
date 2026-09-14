"""Identity resolution for the API (Stytch B2B), behind the AUTH_ENABLED flag.

Identity resolves ONCE per request, here, into a `Principal`. Routes take it
as a FastAPI dependency and scope every read/write on it; the worker receives
the same values through WorkflowInput and never re-derives them.

    AUTH_ENABLED=false (default)  -> every request is the fixed LEGACY principal.
                                     Behavior is byte-identical to pre-auth.
    AUTH_ENABLED=true             -> the Stytch session is verified and
                                     member_session -> Principal.

Verification is HYBRID by route (see docs/STYTCH_NOTES.md for the verified
SDK surface):

  * get_principal      — hot paths (reads, run creation, streaming). Verifies
                         the session JWT locally against the cached JWKS via
                         sessions.authenticate_jwt_async: no network per
                         request. Revocation lags by at most the JWT lifetime
                         (5 min).
  * reverify_network   — sensitive, rare routes (org-skill trust / enable /
                         delete). Calls sessions.authenticate_async with the
                         opaque X-Session-Token so a revoked session fails
                         immediately, and passes an AuthorizationCheck so the
                         RBAC decision is made by Stytch, not by us.

The frontend therefore sends BOTH headers on every request:
    Authorization: Bearer <session_jwt>
    X-Session-Token: <session_token>

Tenancy is row scoping in the JSON stores (backend/store.py seam). This is
dev/staging auth. Production row-level security (Postgres RLS) is a
separately tracked step and is deliberately NOT introduced here.
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

SESSION_TOKEN_HEADER = "x-session-token"

# RBAC resource/action the org-skill management routes check. Must exist in
# the Stytch dashboard's RBAC policy with stytch_admin granted "manage" (a
# manual dashboard step — see docs/HOW_TO_RUN.md).
ORG_SKILLS_RESOURCE = "org_skills"
ORG_SKILLS_MANAGE = "manage"
ADMIN_ROLE = "stytch_admin"


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
# request is this principal; with the flag on, the startup backfill
# (store.backfill_identity) stamps pre-auth rows with these ids so old data
# lands in a claimable bucket instead of vanishing from every real tenant's
# view.
LEGACY_USER_ID = "legacy"
LEGACY_ORG_ID = "legacy"
LEGACY_PRINCIPAL = Principal(
    user_id=LEGACY_USER_ID, org_id=LEGACY_ORG_ID, roles=[ADMIN_ROLE]
)


# ---------------------------------------------------------------------------
# Stytch client — ONE per process. B2BClient builds a jwt.PyJWKClient in its
# constructor (STYTCH_NOTES.md "Client"); that object caches the JWKS, so a
# per-request client would refetch keys on every call.
# ---------------------------------------------------------------------------

_client = None  # stytch.B2BClient | None


def _build_client():
    from stytch import B2BClient  # import here: the flag-off path never needs the SDK

    project_id = os.environ.get("STYTCH_PROJECT_ID", "").strip()
    secret = os.environ.get("STYTCH_SECRET", "").strip()
    env = os.environ.get("STYTCH_ENV", "test").strip() or "test"
    if not project_id or not secret:
        # Fail fast and loud: the flag is on but the keys aren't. Falling back
        # to no-auth here would silently disable the whole feature.
        raise RuntimeError(
            "AUTH_ENABLED=true but STYTCH_PROJECT_ID / STYTCH_SECRET are not set"
        )
    with warnings.catch_warnings():
        # The SDK warns "Test version of Stytch not intended for production
        # use" on every test-env construction; that's the intended env here.
        warnings.simplefilter("ignore")
        return B2BClient(project_id=project_id, secret=secret, environment=env)


def get_client():
    """The process-wide B2BClient, built on first use (or at module load when
    the flag is on — see the bottom of this module)."""
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Request -> Principal
# ---------------------------------------------------------------------------

def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _session_token(request: Request) -> str | None:
    tok = request.headers.get(SESSION_TOKEN_HEADER, "").strip()
    return tok or None


def _unauthorized(reason: str) -> HTTPException:
    # One generic message on the wire; the reason goes to the log only, so a
    # probing client can't distinguish "expired" from "forged" from "missing".
    logger.info("auth rejected: %s", reason)
    return HTTPException(status_code=401, detail="unauthorized")


def _principal_from_session(member_session) -> Principal:
    """MemberSession -> Principal. Field names verified in STYTCH_NOTES.md."""
    return Principal(
        user_id=member_session.member_id,
        org_id=member_session.organization_id,
        roles=list(member_session.roles or []),
    )


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency: the caller's identity, verified locally.

    Flag off -> LEGACY. Flag on -> Authorization: Bearer <session_jwt> is
    verified against the cached JWKS (signature, aud, iss, exp/iat/nbf) with no
    network round-trip; an expired-but-signed JWT falls through to one network
    call inside the SDK. ANY failure -> 401.
    """
    if not auth_enabled():
        return LEGACY_PRINCIPAL

    jwt = _bearer(request)
    if not jwt:
        raise _unauthorized("missing bearer")
    client = get_client()
    try:
        # STYTCH_NOTES.md "Local verification": returns AuthenticateJWTLocalResponse
        # with .member_session; local decode failures fall back to the network
        # inside the SDK, which raises StytchError on a dead session.
        resp = await client.sessions.authenticate_jwt_async(session_jwt=jwt)
    except Exception as e:  # StytchError, PyJWKClientError, ValueError, network
        raise _unauthorized(f"jwt verification failed: {type(e).__name__}: {e}") from None
    ms = getattr(resp, "member_session", None)
    if ms is None:
        raise _unauthorized("no member_session in response")
    return _principal_from_session(ms)


async def reverify_network(request: Request, principal: Principal,
                           *, resource_id: str = ORG_SKILLS_RESOURCE,
                           action: str = ORG_SKILLS_MANAGE) -> Principal:
    """Network-backed re-verification for sensitive routes.

    Uses the opaque X-Session-Token with sessions.authenticate_async (STYTCH_
    NOTES.md "Network verification"): a revoked session fails here instantly,
    whereas a still-signed JWT would pass the local check for up to 5 minutes.
    The AuthorizationCheck is evaluated by Stytch against the org's RBAC policy;
    a member without a granting role gets a 403 from Stytch, which we forward
    as 403. The returned Principal is the FRESH one from this call and must
    match the locally-verified one (defense against header mix-and-match).

    Flag off -> returns the principal unchanged (no network).
    """
    if not auth_enabled():
        return principal

    token = _session_token(request)
    if not token:
        raise _unauthorized("missing X-Session-Token")
    from stytch.b2b.models.sessions import AuthorizationCheck
    from stytch.core.response_base import StytchError

    client = get_client()
    try:
        resp = await client.sessions.authenticate_async(
            session_token=token,
            authorization_check=AuthorizationCheck(
                organization_id=principal.org_id,
                resource_id=resource_id,
                action=action,
            ),
        )
    except StytchError as e:
        status = getattr(getattr(e, "details", None), "status_code", None)
        if status == 403:
            logger.info("rbac denied %s/%s for member %s", resource_id, action, principal.user_id)
            raise HTTPException(status_code=403, detail="forbidden") from None
        raise _unauthorized(f"session_token verification failed: {status}") from None
    except Exception as e:
        raise _unauthorized(f"session_token verification error: {type(e).__name__}") from None

    fresh = _principal_from_session(resp.member_session)
    if fresh.user_id != principal.user_id or fresh.org_id != principal.org_id:
        # The bearer JWT and the session token belong to different sessions.
        raise _unauthorized("bearer/session-token identity mismatch")
    return fresh


def require_role(principal: Principal, role: str = ADMIN_ROLE) -> None:
    """Authenticated-but-not-allowed -> 403. No-op when the flag is off (the
    LEGACY principal carries stytch_admin anyway, so this is belt-and-braces)."""
    if not auth_enabled():
        return
    if not principal.has_role(role):
        raise HTTPException(status_code=403, detail="forbidden")


# Build the client at module load when the flag is on, so a misconfigured
# deployment fails at boot rather than on the first request.
if auth_enabled():
    get_client()

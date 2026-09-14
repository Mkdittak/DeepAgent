# Stytch B2B SDK — verified surface (installed `stytch==15.3.0`)

Every name below was read from the installed package in `.venv`, not from
docs or memory. Paths are relative to `.venv/Lib/site-packages/stytch/`.
Everything in `backend/auth.py` cites this file; if the SDK is upgraded,
re-verify these and update here first.

## Client

| Item | Verified value | Source |
|---|---|---|
| Import | `from stytch import B2BClient` (alias of `stytch.b2b.client.Client`) | `__init__.py` |
| Init | `B2BClient(project_id: str, secret: str, environment: str \| None = None, suppress_warnings: bool = False, sync_session=None, async_session=None, fraud_environment=None, custom_base_url=None)` | `b2b/client.py:44-54` |
| `environment` | `"test"` -> `https://test.stytch.com/`, `"live"` -> `https://api.stytch.com/`. `None` infers from the `project-live-` id prefix. `"test"` emits a `UserWarning` unless `suppress_warnings=True`. | `core/client_base.py:52-90` |
| JWKS | Built once in `ClientBase.__init__` as `jwt.PyJWKClient(<api_base>/v1/b2b/sessions/jwks/{project_id})` and stored on `client.jwks_client`. PyJWKClient caches keys, so the client must be a module-level singleton. | `core/client_base.py:36`, `b2b/client.py:178-181` |
| RBAC policy cache | `PolicyCache(RBAC(...))` built in the client init and shared into `client.sessions`; refreshes every 10 min; merges project + org policies via `get_with_org(_async)`. | `b2b/client.py:66-72`, `shared/policy_cache.py` |
| Cleanup | `await client.close()` (or `async with`). | `core/client_base.py:38-46` |

## Sessions — `client.sessions` (`b2b/api/sessions.py`)

Every method has a sync form and an `_async` twin with the same params.

### Local verification (hot path)

```
client.sessions.authenticate_jwt_async(
    session_jwt: str,
    max_token_age_seconds: int | None = None,
    session_custom_claims: dict | None = None,
    authorization_check: AuthorizationCheck | None = None,
) -> AuthenticateJWTLocalResponse      # .member_session, .session_jwt
```
`sessions.py:858-911`. Behavior:

1. Calls `authenticate_jwt_local_async(...)`, which verifies the RS256 signature
   against the cached JWKS, checks `aud == project_id`, `iss in
   {"stytch.com/<project_id>", <api_base>}`, and `exp/iat/nbf`
   (`shared/jwt_helpers.py:68-130`). Any decode failure returns `None`
   (never raises) — expired, forged, garbage, wrong project all land here.
2. If `max_token_age_seconds` is set and `now - iat >= max_token_age_seconds`,
   the local result is discarded (`jwt_helpers.py:111-115`). **`0` therefore
   forces the network path for every token** (docstring at `sessions.py:816-823`
   says the same).
3. On `None` it falls back to `authenticate_async(session_jwt=..., authorization_check=...)`
   over the network and re-wraps the result.

`authenticate_jwt_local_async` (`sessions.py:1056-1087`) returns
`MemberSession | None`. Roles come from the JWT's
`https://stytch.com/session` claim (`roles`); org from
`https://stytch.com/organization` (`organization_id`, `slug`); `member_id`
from `sub` (`sessions.py:969-1022`).

### Network verification (sensitive routes)

```
client.sessions.authenticate_async(
    session_token: str | None = None,
    session_duration_minutes: int | None = None,
    session_jwt: str | None = None,
    session_custom_claims: dict | None = None,
    authorization_check: AuthorizationCheck | dict | None = None,
) -> AuthenticateResponse   # .member_session, .session_token, .session_jwt, .member, .organization, .verdict
```
`sessions.py:165-234`. POSTs `/v1/b2b/sessions/authenticate`. Exactly one of
`session_token` / `session_jwt` must be given (API errors if both). A revoked
session fails here immediately, which is the point of using it on rare
sensitive routes.

**Decision:** the sensitive path calls `authenticate_async(session_token=<X-Session-Token>)`.
Both `authenticate_jwt_async(..., max_token_age_seconds=0)` and
`authenticate_async(session_jwt=...)` also hit the network, but passing the
opaque session token is the form that cannot be satisfied by a stale-but-
signed JWT, so it is the one that guarantees revocation is honored.

### Errors

Network calls raise `stytch.core.response_base.StytchError` on any 4xx/5xx
(`response_base.py:14-31, 86`). `err.details.status_code`,
`err.details.error_type`, `err.details.error_message` are available. Local
RBAC failures raise `stytch.shared.rbac_local.RBACPermissionError` or
`TenancyError` (both `ValueError` subclasses, `rbac_local.py:15-32`).
`get_signing_key_from_jwt` can raise `jwt.exceptions.PyJWKClientError`
(malformed header / unknown kid) **before** the try/except in
`jwt_helpers._authenticate_jwt_local`, so the caller must catch broadly.

## MemberSession (`b2b/models/sessions.py:77-101`)

Pydantic model. Fields the backend uses:

| Attribute | Type | Maps to |
|---|---|---|
| `member_id` | `str` | `Principal.user_id` |
| `organization_id` | `str` | `Principal.org_id` |
| `roles` | `list[str]` | `Principal.roles` (e.g. `"stytch_admin"`, `"stytch_member"`) |
| `organization_slug` | `str` | display only |
| `member_session_id`, `started_at`, `last_accessed_at`, `expires_at`, `authentication_factors`, `custom_claims` | — | unused |

## AuthorizationCheck (`b2b/models/sessions.py:42-63`)

```
from stytch.b2b.models.sessions import AuthorizationCheck
AuthorizationCheck(organization_id: str, resource_id: str, action: str)
```
Passed as `authorization_check=` to either authenticate method. The
`organization_id` **must** equal the session's org or the check fails
(`TenancyError` locally, HTTP 403 remotely). `resource_id` may not start
with `stytch`. Local evaluation: `rbac_local.is_authorized` (`rbac_local.py:204-224`)
matches a role in `subject_roles` whose permission has the same `resource_id`
and an action equal to the requested one or `"*"`. `stytch_admin` is the
built-in org-admin role; the dashboard step "define `org_skills` resource with
a `manage` action and confirm `stytch_admin` covers it" is what makes
`AuthorizationCheck(org, "org_skills", "manage")` pass for admins.

Response on the network path: `AuthenticateResponse.verdict: AuthorizationVerdict | None`
with `.authorized: bool`, `.granting_roles: list[str]` (`models/sessions.py:66-74`).

"""
Forged / garbage bearer tokens -> 401 from the REAL get_principal.

Exercises backend.auth.get_principal end to end against a real B2BClient
(dummy keys; no network — the JWKS fetch and the network fallback are
replaced with in-process fakes so the outcome is deterministic):

  1. no Authorization header                       -> 401
  2. non-bearer scheme                              -> 401
  3. garbage token (not a JWT)                      -> 401
  4. well-formed JWT signed by an attacker's key   -> 401
  5. correctly signed, but for another project     -> 401 (aud mismatch)
  6. correctly signed, but expired                  -> 401 (network fallback rejects)
  7. control: correctly signed, right project       -> Principal(member, org, roles)

Case 7 proves the negative cases fail for the reason we think (the pipeline
does accept a valid token) and that MemberSession -> Principal maps the
verified field names (docs/STYTCH_NOTES.md).

Run (repo root): .venv\\Scripts\\python.exe tests\\test_forged_jwt.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_harness import REAL_GET_PRINCIPAL, check, finish  # noqa: E402  (sets env + imports backend)

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from stytch.core.response_base import StytchError, StytchErrorDetails  # noqa: E402

from backend import auth  # noqa: E402

PROJECT_ID = os.environ["STYTCH_PROJECT_ID"]


def _keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    return pem, priv.public_key()


STYTCH_PEM, STYTCH_PUB = _keypair()      # "Stytch's" real signing key
ATTACKER_PEM, _ = _keypair()             # a key Stytch has never seen


def _claims(project=PROJECT_ID, member="member-real", org="org-real", roles=("stytch_admin",),
            exp_delta=300):
    now = int(time.time())
    return {
        "aud": project, "iss": f"stytch.com/{project}", "sub": member,
        "iat": now - 5, "nbf": now - 5, "exp": now + exp_delta,
        "https://stytch.com/session": {
            "id": "member-session-1", "started_at": "2026-01-01T00:00:00Z",
            "last_accessed_at": "2026-01-01T00:00:00Z", "expires_at": "2026-12-31T00:00:00Z",
            "authentication_factors": [], "roles": list(roles),
        },
        "https://stytch.com/organization": {"organization_id": org, "slug": "real"},
    }


def _token(pem, **kw):
    return jwt.encode(_claims(**kw), pem, algorithm="RS256", headers={"kid": "k1"})


# --- fake the two network touchpoints on the real client ------------------
client = auth.get_client()
from jwt.algorithms import RSAAlgorithm  # noqa: E402
_stytch_jwk = jwt.PyJWK({**RSAAlgorithm.to_jwk(STYTCH_PUB, as_dict=True), "kid": "k1", "alg": "RS256", "use": "sig"})
client.jwks_client.get_signing_key_from_jwt = lambda token: _stytch_jwk  # JWKS "fetched"

network_calls = []


async def _reject(**kw):
    network_calls.append(kw)
    raise StytchError(StytchErrorDetails.from_unknown(401))


client.sessions.authenticate_async = _reject  # the fallback path always says no


def req(headers: dict) -> Request:
    scope = {"type": "http", "method": "GET", "path": "/",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def resolve(headers: dict):
    try:
        return asyncio.run(REAL_GET_PRINCIPAL(req(headers)))
    except HTTPException as e:
        return e.status_code


check("1 missing header -> 401", resolve({}) == 401)
check("2 non-bearer scheme -> 401", resolve({"Authorization": "Basic abc"}) == 401)
check("3 garbage token -> 401", resolve({"Authorization": "Bearer not.a.jwt"}) == 401)
check("3b empty bearer -> 401", resolve({"Authorization": "Bearer "}) == 401)

n0 = len(network_calls)
check("4 attacker-signed JWT -> 401", resolve({"Authorization": f"Bearer {_token(ATTACKER_PEM)}"}) == 401)
check("5 right key, wrong project (aud) -> 401",
      resolve({"Authorization": f"Bearer {_token(STYTCH_PEM, project='project-test-other')}"}) == 401)
check("6 right key, expired -> 401",
      resolve({"Authorization": f"Bearer {_token(STYTCH_PEM, exp_delta=-60)}"}) == 401)
check("4-6 each fell through to the network fallback, which rejected", len(network_calls) == n0 + 3)

p = resolve({"Authorization": f"Bearer {_token(STYTCH_PEM)}"})
check("7 control: valid token -> Principal", isinstance(p, auth.Principal))
if isinstance(p, auth.Principal):
    check("7 member_id -> user_id", p.user_id == "member-real")
    check("7 organization_id -> org_id", p.org_id == "org-real")
    check("7 roles carried", p.roles == ["stytch_admin"])
check("7 verified locally (no network call)", len(network_calls) == n0 + 3)

# 401 bodies are uniform: a probing client can't tell forged from expired.
def detail(headers):
    try:
        asyncio.run(REAL_GET_PRINCIPAL(req(headers)))
    except HTTPException as e:
        return e.detail
check("401 detail is generic for garbage", detail({"Authorization": "Bearer zzz"}) == "unauthorized")
check("401 detail is generic for forged", detail({"Authorization": f"Bearer {_token(ATTACKER_PEM)}"}) == "unauthorized")

finish()

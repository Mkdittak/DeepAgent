"""Shared setup for the auth/tenancy tests (not a test itself, like sse_client.py).

Builds an isolated FastAPI TestClient against backend.main with:
  * ARTIFACT_BASE pointed at a fresh temp dir (registry, thread + skill
    stores, event logs all land there — nothing touches ./artifacts)
  * AUTH_ENABLED=true (each test can flip it via set_auth(False))
  * get_principal overridden per request (as_(principal)); the real
    resolver is exercised separately by test_forged_jwt.py
  * Temporal + the background persister faked (no server needed)
  * auth.reverify_network stubbed to a recorder (no Stytch network calls);
    the real function is unit-tested against a fake client in test_admin_gate

Usage:
    from auth_harness import Harness
    h = Harness()
    h.as_(h.A); r = h.c.post("/runs", json={"message": "hi"})
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set BEFORE backend.main / backend.store are imported (both read
# ARTIFACT_BASE at import time).
_TMP = tempfile.mkdtemp(prefix="deepagent-auth-test-")
os.environ["ARTIFACT_BASE"] = _TMP
os.environ["AUTH_ENABLED"] = "true"
# Dummy Stytch keys so the module-load client build succeeds without .env.
# No network call happens at construction (PyJWKClient is lazy).
os.environ.setdefault("STYTCH_PROJECT_ID", "project-test-00000000-0000-0000-0000-000000000000")
os.environ.setdefault("STYTCH_SECRET", "secret-test-not-real")
os.environ.setdefault("STYTCH_ENV", "test")
os.environ["ARTIFACT_SIGNING_SECRET"] = "test-signing-secret"

from fastapi.testclient import TestClient  # noqa: E402

import backend.main as m  # noqa: E402
from backend import auth, store  # noqa: E402
from backend.auth import Principal, get_principal  # noqa: E402

SKILL_MD = "---\nname: {name}\ndescription: test skill\n---\n# body\n"

# The real network re-verifier, captured before Harness() stubs it, for
# tests that exercise it directly against a fake Stytch client.
REAL_REVERIFY = auth.reverify_network
REAL_GET_PRINCIPAL = auth.get_principal


class _FakeHandle:
    async def cancel(self):
        return None


class _FakeTemporal:
    def __init__(self, started: list):
        self._started = started

    async def start_workflow(self, fn, wi, **kw):
        self._started.append(wi)

    def get_workflow_handle(self, wf_id):
        return _FakeHandle()


class Harness:
    A = Principal("member-A", "org-X", ["stytch_admin"])  # org X admin
    B = Principal("member-B", "org-X", ["stytch_member"])  # org X plain member
    C = Principal("member-C", "org-Y", ["stytch_admin"])  # org Y admin

    def __init__(self):
        self.m = m
        self.auth = auth
        self.store = store
        self.tmp = _TMP
        self.started: list = []  # WorkflowInputs handed to Temporal
        self.reverify_calls: list = []  # principals that hit the network path
        self._who = {"p": self.A}

        m.app.dependency_overrides[get_principal] = lambda: self._who["p"]
        fake = _FakeTemporal(self.started)

        async def _client():
            return fake

        async def _persist(*a, **k):
            return None

        async def _reverify(request, principal, **kw):
            self.reverify_calls.append(principal)
            return principal

        m.get_temporal_client = _client
        m._persist_run = _persist
        auth.reverify_network = _reverify
        self.c = TestClient(m.app)

    # -- identity / flag -------------------------------------------------
    def as_(self, p: Principal) -> None:
        self._who["p"] = p

    @staticmethod
    def set_auth(on: bool) -> None:
        os.environ["AUTH_ENABLED"] = "true" if on else "false"

    # -- fixtures ----------------------------------------------------------
    def run(self, message: str = "hello", thread_id: str | None = None) -> dict:
        body = {"message": message}
        if thread_id:
            body["thread_id"] = thread_id
        r = self.c.post("/runs", json=body)
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    def artifact(self, run_id: str, filename: str, content: str = "x") -> str:
        d = os.path.join(self.tmp, run_id)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, filename)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def install(self, name: str, tier: str) -> str:
        r = self.c.post("/skills", json={"body": SKILL_MD.format(name=name), "tier": tier})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["skill_id"]

    def skill_names(self) -> list[str]:
        return sorted(s["name"] for s in self.c.get("/skills").json() if s["tier"] != "built-in")


failures: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    if not ok:
        failures.append(label)


def finish() -> None:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)

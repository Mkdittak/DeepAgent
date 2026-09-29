"""Issue #1 — run_id collision at 1-second granularity.

Two runs with a similar prompt inside one wall-clock second used to get the
same run_id/workflow_id: the second either 500'd (WorkflowAlreadyStartedError
uncaught) or silently appended into the first run's event log, where offset
dedup dropped every event. Fix: a 6-hex random suffix on the id, a 409 (not
500) if Temporal still reports a duplicate, and the registry row rolled back.

pytest-style (collected by `pytest tests/test_run_id.py`). Uses auth_harness
for the fake Temporal client + isolated ARTIFACT_BASE.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from temporalio.exceptions import WorkflowAlreadyStartedError  # noqa: E402

from auth_harness import Harness  # noqa: E402  (sets ARTIFACT_BASE before backend import)
from backend import store  # noqa: E402
from backend.main import _make_run_id  # noqa: E402

RUN_ID_RE = re.compile(r"^[a-z0-9-]*_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[0-9a-f]{6}$")


def test_run_ids_unique_within_one_second():
    ids = {_make_run_id("make a ppt on climate change") for _ in range(2000)}
    assert len(ids) == 2000, "same prompt, same second must still yield distinct ids"
    assert all(RUN_ID_RE.match(i) for i in ids), next(i for i in ids if not RUN_ID_RE.match(i))


def test_run_id_slug_is_bounded_and_safe():
    rid = _make_run_id("!!! " + "word " * 50 + "../../etc/passwd")
    assert RUN_ID_RE.match(rid)
    assert len(rid.split("_")[0]) <= 40
    assert _make_run_id("").startswith("run_")


def test_store_parses_new_and_legacy_ids():
    legacy = "make-a-ppt_2026-09-01_10-00-00"
    new = "make-a-ppt_2026-09-01_10-00-00_ab12cd"
    for rid in (legacy, new):
        assert store._readable(rid, "") == "Make a ppt", rid
        assert store._run_created_at(rid, {}) == "2026-09-01T10:00:00", rid
    # explicit created_at still wins over the parsed tail
    assert store._run_created_at(new, {"created_at": "X"}) == "X"


def test_duplicate_workflow_id_is_409_and_registry_rolled_back():
    h = Harness()
    h.as_(h.A)

    async def already_started(fn, wi, **kw):
        raise WorkflowAlreadyStartedError(kw.get("id", "?"), "AgentWorkflow")

    fake_client = h.m.get_temporal_client  # coroutine returning the fake
    import asyncio
    client = asyncio.run(fake_client())
    client.start_workflow = already_started

    before = set(h.m.run_registry)
    r = h.c.post("/runs", json={"message": "dup me"})
    assert r.status_code == 409, r.text
    assert "already in progress" in r.json()["error"]
    # no stale 'running' row in memory ...
    assert set(h.m.run_registry) == before
    # ... nor on disk
    on_disk = json.loads(Path(h.m.REGISTRY_FILE).read_text(encoding="utf-8")) \
        if Path(h.m.REGISTRY_FILE).exists() else {}
    assert not any(v.get("user_message") == "dup me" for v in on_disk.values())


def test_normal_start_still_works_after_duplicate_path():
    h = Harness()
    h.as_(h.A)
    r1 = h.c.post("/runs", json={"message": "same prompt"})
    r2 = h.c.post("/runs", json={"message": "same prompt"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["run_id"] != r2.json()["run_id"]
    assert r1.json()["workflow_id"] != r2.json()["workflow_id"]
    # both rows survive in the registry (the old code overwrote the first)
    assert r1.json()["run_id"] in h.m.run_registry
    assert r2.json()["run_id"] in h.m.run_registry

"""
Run registry robustness: a corrupt .run_registry.json is quarantined as
*.corrupt instead of crashing load, and _save_registry writes atomically
(temp file + os.replace, no leftover .tmp).

Run (repo root): python tests/test_registry.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.main as m


def test_registry_corrupt_load_and_atomic_save():
    tmpdir = tempfile.mkdtemp()
    reg = os.path.join(tmpdir, ".run_registry.json")
    with open(reg, "w", encoding="utf-8") as f:
        f.write('{"run-a": {"workflow_id": "agent-run-a", trunc')  # truncated JSON

    # Point the module at the throwaway file and load it the way import does.
    orig = (m.REGISTRY_FILE, m.ARTIFACT_BASE, dict(m.run_registry))
    m.REGISTRY_FILE, m.ARTIFACT_BASE = reg, tmpdir
    m.run_registry.clear()
    try:
        m._load_registry()
        corrupt = reg + ".corrupt"
        print("corrupt file preserved:", os.path.isfile(corrupt))
        print("entries recovered:", dict(m.run_registry))
        assert os.path.isfile(corrupt), "corrupt registry was not preserved as .corrupt"
        assert "run-a" not in m.run_registry

        m.run_registry["run-b"] = {
            "workflow_id": "agent-run-b",
            "user_message": "hi",
            "status": "done",
        }
        m._save_registry()
        with open(reg, encoding="utf-8") as f:
            loaded = json.load(f)
        print("atomic save valid JSON, run-b present:", "run-b" in loaded)
        assert "run-b" in loaded
        assert not os.path.isfile(reg + ".tmp"), "leftover .tmp after atomic save"
    finally:
        m.REGISTRY_FILE, m.ARTIFACT_BASE = orig[0], orig[1]
        m.run_registry.clear()
        m.run_registry.update(orig[2])


if __name__ == "__main__":
    test_registry_corrupt_load_and_atomic_save()

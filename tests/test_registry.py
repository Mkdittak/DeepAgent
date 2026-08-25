import os
import json
import tempfile

# Isolate: point the registry at a throwaway dir BEFORE importing the module.
tmpdir = tempfile.mkdtemp()
os.environ["ARTIFACT_BASE"] = tmpdir

# Plant a corrupt registry file.
reg = os.path.join(tmpdir, ".run_registry.json")
with open(reg, "w", encoding="utf-8") as f:
    f.write('{"run-a": {"workflow_id": "agent-run-a", trunc')  # truncated JSON

import backend.main as m  # import triggers _load_registry()

corrupt = reg + ".corrupt"
print("corrupt file preserved:", os.path.isfile(corrupt))
print("registry did NOT crash load; entries recovered:", dict(m.run_registry))

# Now prove atomic save round-trips.
m.run_registry["run-b"] = {"workflow_id": "agent-run-b", "user_message": "hi", "status": "done"}
m._save_registry()
with open(reg, encoding="utf-8") as f:
    loaded = json.load(f)
print("atomic save valid JSON, run-b present:", "run-b" in loaded)
print("no leftover .tmp:", not os.path.isfile(reg + ".tmp"))

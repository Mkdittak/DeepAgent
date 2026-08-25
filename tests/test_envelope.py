from backend.main import _v1_envelope
from temporal.activities import AgentProgress


def ap(**kw):
    kw.setdefault("seq", 0)
    kw.setdefault("ts", "2026-08-25T00:00:00Z")
    kw.setdefault("run_id", "r1")
    kw.setdefault("label", "")
    return AgentProgress(**kw)


cases = [
    ap(type="run_start", label="Make a PPT"),
    ap(type="llm_token", label="Hello "),
    ap(type="tool_start", tool="web_search", step_id="s1", args={"query": "x"}),
    ap(type="tool_progress", tool="web_search", step_id="s1", label="Read: foo"),
    ap(type="tool_end", tool="web_search", step_id="s1", output_preview="[...]", duration_ms=1200),
    ap(type="plan", todos=[{"content": "step 1", "status": "in_progress"}]),
    ap(type="file", artifacts=["index.html"]),
    ap(type="error", label="ValueError: boom"),
    ap(type="done", label="All done", artifacts=["index.html"]),
    ap(type="cancelled", label="cancelled"),
]

for c in cases:
    env = _v1_envelope(5, c, "r1")
    assert env["v"] == 1 and env["offset"] == 5 and env["user_id"] is None and env["org_id"] is None
    print(f"{c.type:12} -> {env['type']:16} keys={sorted(k for k in env if k not in ('v','run_id','offset','ts','user_id','org_id'))}")
print("all envelope mappings carry v1 + null identity fields: OK")

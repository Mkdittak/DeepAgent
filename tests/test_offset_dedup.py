"""Faithful port of App.tsx reduceEvent dedup + run_start/llm_token branches
(App.tsx:64-66 dedup, :101-127 run_start/llm_token), to compare the OLD
seq-based dedup vs the NEW offset-based dedup across a worker-kill + retry.
"""


def reduce(events, key_name):
    turns = []
    seen = set()
    for data in events:
        key = data.get(key_name, data.get("seq", -1))
        if key is not None and key >= 0:
            if key in seen:
                continue  # dropped as duplicate
            seen.add(key)
        et = data.get("event_type", "")
        if et == "run_start":
            turns.append({"role": "assistant", "text": ""})
        elif et == "llm_token":
            # append to current assistant turn's text
            if turns and turns[-1]["role"] == "assistant":
                turns[-1]["text"] += data.get("label", "")
            else:
                turns.append({"role": "assistant", "text": data.get("label", "")})
    return [t["text"] for t in turns if t["role"] == "assistant"]


# Attempt 1 streams a partial answer, then the worker is killed.
# Attempt 2 (Temporal retry) restarts seq at 0 but the durable log keeps
# assigning fresh, higher offsets.
events = [
    {"offset": 0, "seq": 0, "event_type": "run_start", "label": "Q"},
    {"offset": 1, "seq": 1, "event_type": "llm_token", "label": "The capital of Fra"},
    {"offset": 2, "seq": 2, "event_type": "llm_token", "label": "nce is Par"},
    # --- worker killed here; Temporal retries the activity ---
    {"offset": 3, "seq": 0, "event_type": "run_start", "label": "Q"},
    {"offset": 4, "seq": 1, "event_type": "llm_token", "label": "Paris is the capital "},
    {"offset": 5, "seq": 2, "event_type": "llm_token", "label": "of France."},
]

print("OLD dedup by seq :", reduce(events, "seq"))
print("NEW dedup by offset:", reduce(events, "offset"))

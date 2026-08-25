import { useSyncExternalStore } from "react";
import type { Block, Run, Todo, Turn, V1Event } from "./types";

// ---------------------------------------------------------------------------
// State shape: normalized by run_id, runs ordered for persistent scrollback.
// Updates are granular & immutable — untouched turn/block object refs are
// preserved so memoized components skip re-render (only the active text block
// re-renders while streaming). No deep-clone of all turns per event.
// ---------------------------------------------------------------------------

export interface State {
  threadId: string | null;
  order: string[]; // run ids in submit order
  runs: Record<string, Run>;
  connected: boolean;
}

const PERSIST_KEY = "deepagent_session_v1";

function emptyState(): State {
  return { threadId: null, order: [], runs: {}, connected: false };
}

let state: State = emptyState();
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function getState(): State {
  return state;
}

function setState(next: State) {
  state = next;
  persist();
  emit();
}

// ---- persistence (for refresh-resume + scrollback survival) ----

function persist() {
  try {
    const runs: Record<string, unknown> = {};
    for (const [id, r] of Object.entries(state.runs)) {
      runs[id] = { runId: r.runId, turns: r.turns, state: r.state, lastOffset: r.lastOffset };
    }
    localStorage.setItem(
      PERSIST_KEY,
      JSON.stringify({ threadId: state.threadId, order: state.order, runs })
    );
  } catch {
    /* localStorage unavailable — degrade to in-memory only */
  }
}

export function loadPersisted(): State {
  try {
    const raw = localStorage.getItem(PERSIST_KEY);
    if (!raw) return emptyState();
    const p = JSON.parse(raw);
    const runs: Record<string, Run> = {};
    for (const [id, r] of Object.entries(p.runs ?? {}) as [string, any][]) {
      runs[id] = {
        runId: r.runId,
        turns: r.turns ?? [],
        state: r.state ?? "done",
        lastOffset: r.lastOffset ?? -1,
        seenOffsets: new Set<number>(),
      };
    }
    return {
      threadId: p.threadId ?? null,
      order: p.order ?? [],
      runs,
      connected: false,
    };
  } catch {
    return emptyState();
  }
}

export function hydrate() {
  state = loadPersisted();
  emit();
}

// ---- store mutations ----

export function setThreadId(id: string | null) {
  setState({ ...state, threadId: id });
}

export function setConnected(c: boolean) {
  if (state.connected === c) return;
  setState({ ...state, connected: c });
}

export function registerRun(runId: string) {
  if (state.runs[runId]) return;
  const run: Run = {
    runId,
    turns: [],
    state: "streaming",
    lastOffset: -1,
    seenOffsets: new Set(),
  };
  setState({
    ...state,
    runs: { ...state.runs, [runId]: run },
    order: state.order.includes(runId) ? state.order : [...state.order, runId],
  });
}

// Add the user's message immediately (optimistic) so it shows before run.started.
export function addUserTurn(runId: string, text: string) {
  const run = state.runs[runId];
  if (!run) return;
  const already = run.turns.some((t) => t.role === "user" && t.text === text);
  if (already) return;
  const turns = [...run.turns, { id: `${runId}:user`, role: "user", text } as Turn];
  setState({ ...state, runs: { ...state.runs, [runId]: { ...run, turns } } });
}

// ---------------------------------------------------------------------------
// Event reduction — granular immutable updates
// ---------------------------------------------------------------------------

function lastAssistant(turns: Turn[]): number {
  for (let i = turns.length - 1; i >= 0; i--) if (turns[i].role === "assistant") return i;
  return -1;
}

// Apply fn to the last assistant turn (creating one if none), returning a new
// turns array where every other turn keeps its object reference.
function withAssistant(
  turns: Turn[],
  fn: (blocks: Block[]) => Block[],
  statePatch?: (t: Extract<Turn, { role: "assistant" }>) => Partial<Extract<Turn, { role: "assistant" }>>
): Turn[] {
  let idx = lastAssistant(turns);
  let next = turns;
  if (idx === -1) {
    const t: Turn = { id: `a-${turns.length}`, role: "assistant", blocks: [], state: "streaming" };
    next = [...turns, t];
    idx = next.length - 1;
  }
  const cur = next[idx] as Extract<Turn, { role: "assistant" }>;
  const blocks = fn(cur.blocks);
  const patched = statePatch ? statePatch(cur) : {};
  const newTurn = { ...cur, blocks, ...patched };
  const out = next.slice();
  out[idx] = newTurn;
  return out;
}

function reduce(run: Run, ev: V1Event): Run {
  let turns = run.turns;
  let runState = run.state;

  switch (ev.type) {
    case "run.started": {
      if (ev.prompt && !turns.some((t) => t.role === "user" && t.text === ev.prompt)) {
        turns = [...turns, { id: `${run.runId}:user`, role: "user", text: ev.prompt }];
      }
      turns = [...turns, { id: `a-${turns.length}`, role: "assistant", blocks: [], state: "streaming" }];
      break;
    }
    case "text.delta": {
      turns = withAssistant(turns, (blocks) => {
        const last = blocks[blocks.length - 1];
        if (last && last.kind === "text") {
          const nb = { ...last, text: last.text + ev.text };
          return [...blocks.slice(0, -1), nb];
        }
        return [...blocks, { kind: "text", id: `t-${ev.offset}`, text: ev.text }];
      });
      break;
    }
    case "tool.started": {
      turns = withAssistant(turns, (blocks) => [
        ...blocks,
        {
          kind: "tool",
          id: ev.step_id || `tool-${ev.offset}`,
          stepId: ev.step_id,
          name: ev.name,
          args: ev.args ?? null,
          status: "running",
          progress: [],
        },
      ]);
      break;
    }
    case "tool.progress": {
      turns = withAssistant(turns, (blocks) =>
        blocks.map((b) =>
          b.kind === "tool" && b.stepId === ev.step_id
            ? { ...b, progress: [...b.progress, ev.message] }
            : b
        )
      );
      break;
    }
    case "tool.finished": {
      turns = withAssistant(turns, (blocks) =>
        blocks.map((b) =>
          b.kind === "tool" && b.stepId === ev.step_id
            ? { ...b, status: "done", output: ev.output_preview, durationMs: ev.duration_ms }
            : b
        )
      );
      break;
    }
    case "plan.snapshot": {
      // One panel updated in place — replace the single plan block's todos.
      turns = withAssistant(turns, (blocks) => {
        const existing = blocks.findIndex((b) => b.kind === "plan");
        if (existing >= 0) {
          const nb = { ...(blocks[existing] as Extract<Block, { kind: "plan" }>), todos: ev.todos };
          const out = blocks.slice();
          out[existing] = nb;
          return out;
        }
        return [...blocks, { kind: "plan", id: `${run.runId}:plan`, todos: ev.todos }];
      });
      break;
    }
    case "file.created": {
      turns = withAssistant(turns, (blocks) => {
        if (blocks.some((b) => b.kind === "artifact" && b.filename === ev.filename)) return blocks;
        return [...blocks, { kind: "artifact", id: `f-${ev.filename}`, filename: ev.filename, url: ev.url }];
      });
      break;
    }
    case "run.error": {
      turns = withAssistant(
        turns,
        (blocks) => [...blocks, { kind: "error", id: `e-${ev.offset}`, message: ev.message }],
        () => ({ state: "error" })
      );
      runState = "error";
      break;
    }
    case "run.finished": {
      turns = withAssistant(
        turns,
        (blocks) => {
          // append any artifacts not already shown
          const arts = (ev.artifacts ?? []).filter(
            (fn) => !blocks.some((b) => b.kind === "artifact" && b.filename === fn)
          );
          return arts.length
            ? [
                ...blocks,
                ...arts.map(
                  (fn) =>
                    ({ kind: "artifact", id: `f-${fn}`, filename: fn, url: `/artifacts/${run.runId}/${fn}` }) as Block
                ),
              ]
            : blocks;
        },
        () => ({ state: ev.state })
      );
      runState = ev.state;
      break;
    }
  }

  return { ...run, turns, state: runState };
}

export function applyEvent(ev: V1Event) {
  const runId = ev.run_id;
  const existing = state.runs[runId];
  const run: Run = existing ?? {
    runId,
    turns: [],
    state: "streaming",
    lastOffset: -1,
    seenOffsets: new Set(),
  };
  if (ev.offset >= 0 && run.seenOffsets.has(ev.offset)) return; // dedup by offset
  const seen = new Set(run.seenOffsets);
  if (ev.offset >= 0) seen.add(ev.offset);
  const reduced = reduce(run, ev);
  const nextRun: Run = {
    ...reduced,
    lastOffset: Math.max(run.lastOffset, ev.offset),
    seenOffsets: seen,
  };
  setState({
    ...state,
    runs: { ...state.runs, [runId]: nextRun },
    order: state.order.includes(runId) ? state.order : [...state.order, runId],
  });
}

// ---------------------------------------------------------------------------
// React binding — subscribe by slice
// ---------------------------------------------------------------------------

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => selector(state)
  );
}

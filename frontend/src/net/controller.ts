import { startRun, cancelRun, getThread } from "./api";
import { openRunStream, type StreamHandle } from "./sse";
import * as store from "../store/store";

// Owns the SSE connections and the submit/cancel/resume/thread lifecycle. One
// stream per active run; multiple tabs each run their own controller.

const streams = new Map<string, StreamHandle>();
let activeRunId: string | null = null;

// Open a run's stream. `live` runs (the current one) drive the connection dot;
// replay opens (loading a finished thread) don't. Resolves when the stream ends.
function open(runId: string, fromOffset: number | null, live: boolean): Promise<void> {
  if (live) store.setConnected(true);
  return new Promise((resolve) => {
    const handle = openRunStream(
      runId,
      fromOffset,
      (ev) => store.applyEvent(ev),
      () => {
        streams.delete(runId);
        if (live && streams.size === 0) store.setConnected(false);
        resolve();
      }
    );
    streams.set(runId, handle);
  });
}

function stopAll() {
  for (const h of streams.values()) h.stop();
  streams.clear();
  store.setConnected(false);
  activeRunId = null;
}

export async function submit(message: string) {
  const threadId = store.getState().threadId;
  const { run_id, thread_id } = await startRun(message, threadId);
  store.setThreadId(thread_id);
  store.registerRun(run_id);
  store.addUserTurn(run_id, message);
  activeRunId = run_id;
  void open(run_id, null, true);
}

export async function cancel() {
  if (activeRunId) await cancelRun(activeRunId);
}

export function newChat() {
  stopAll();
  store.reset();
}

// Load a thread's full conversation: replay each finished run from disk in
// order, and attach live to the last run if it's still running.
export async function loadThread(threadId: string) {
  stopAll();
  store.reset();
  store.setThreadId(threadId);
  const detail = await getThread(threadId);
  if (!detail) return;
  for (let i = 0; i < detail.runs.length; i++) {
    const run = detail.runs[i];
    const isLast = i === detail.runs.length - 1;
    if (isLast && run.status === "running") {
      activeRunId = run.run_id;
      void open(run.run_id, null, true);
    } else {
      await open(run.run_id, null, false);
    }
  }
}

// Reconnect to a single run (kept for completeness / deep links).
export function reconnect(runId: string) {
  if (streams.has(runId)) return;
  store.registerRun(runId);
  activeRunId = runId;
  void open(runId, null, true);
}

// On page load: resume any run that was mid-stream when we were last here.
export function resumeOnLoad() {
  const s = store.getState();
  for (const id of s.order) {
    const r = s.runs[id];
    if (r && r.state === "streaming" && !streams.has(id)) {
      activeRunId = id;
      void open(id, r.lastOffset >= 0 ? r.lastOffset : null, true);
    }
  }
}

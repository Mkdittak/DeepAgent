import { startRun, cancelRun } from "./api";
import { openRunStream, type StreamHandle } from "./sse";
import * as store from "../store/store";

// Owns the SSE connections and the submit/cancel/resume lifecycle. One stream
// per active run; multiple tabs each run their own controller independently.

const streams = new Map<string, StreamHandle>();
let activeRunId: string | null = null;

function openStreamFor(runId: string, fromOffset: number | null) {
  store.setConnected(true);
  const handle = openRunStream(
    runId,
    fromOffset,
    (ev) => store.applyEvent(ev),
    () => {
      streams.delete(runId);
      if (streams.size === 0) store.setConnected(false);
    }
  );
  streams.set(runId, handle);
}

export async function submit(message: string) {
  const threadId = store.getState().threadId;
  const { run_id, thread_id } = await startRun(message, threadId);
  store.setThreadId(thread_id);
  store.registerRun(run_id);
  store.addUserTurn(run_id, message);
  activeRunId = run_id;
  openStreamFor(run_id, null);
}

export async function cancel() {
  if (activeRunId) await cancelRun(activeRunId);
}

// Reconnect to a run (from Past Runs): attaches live if still running, replays
// from offset 0 otherwise. Intentional change vs legacy snapshot-only reconnect.
export function reconnect(runId: string) {
  if (streams.has(runId)) return;
  store.registerRun(runId);
  activeRunId = runId;
  openStreamFor(runId, null);
}

// On page load: resume any run that was mid-stream when we were last here.
export function resumeOnLoad() {
  const s = store.getState();
  for (const id of s.order) {
    const r = s.runs[id];
    if (r && r.state === "streaming" && !streams.has(id)) {
      activeRunId = id;
      openStreamFor(id, r.lastOffset >= 0 ? r.lastOffset : null);
    }
  }
}

import type { RunSummary } from "../store/types";

// API origin. Configurable via VITE_API_BASE so the app isn't pinned to the
// build machine: set it to "" for same-origin (relative URLs behind a reverse
// proxy) or to a full origin. Defaults to the current host on :8000 for the
// standard split dev setup (frontend :3000, backend :8000).
const _envBase = import.meta.env.VITE_API_BASE;
export const API_BASE =
  _envBase !== undefined ? _envBase : `http://${window.location.hostname}:8000`;

export async function startRun(
  message: string,
  threadId: string | null
): Promise<{ run_id: string; workflow_id: string; thread_id: string }> {
  const res = await fetch(`${API_BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId ?? undefined }),
  });
  if (!res.ok) throw new Error(`startRun failed: ${res.status}`);
  return res.json();
}

export async function cancelRun(runId: string): Promise<void> {
  await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export async function listRuns(): Promise<RunSummary[]> {
  const res = await fetch(`${API_BASE}/runs`);
  if (!res.ok) return [];
  return res.json();
}

export function artifactUrl(runId: string, filename: string): string {
  return `${API_BASE}/artifacts/${encodeURIComponent(runId)}/${encodeURIComponent(filename)}`;
}

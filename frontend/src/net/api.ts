import type { RunSummary } from "../store/types";

export const API_BASE = `http://${window.location.hostname}:8000`;

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

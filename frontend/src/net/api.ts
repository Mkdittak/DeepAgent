import type { RunSummary, SkillDetail, SkillSummary, ThreadSummary, ThreadDetail } from "../store/types";

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

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await fetch(`${API_BASE}/threads`);
  if (!res.ok) return [];
  return res.json();
}

export async function getThread(threadId: string): Promise<ThreadDetail | null> {
  const res = await fetch(`${API_BASE}/threads/${encodeURIComponent(threadId)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function renameThread(threadId: string, title: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/threads/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return res.ok;
}

export async function deleteThread(threadId: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
  return res.ok;
}

// ---- Skills (agentskills.io) ----

export async function listSkills(): Promise<SkillSummary[]> {
  const res = await fetch(`${API_BASE}/skills`);
  if (!res.ok) return [];
  return res.json();
}

export async function getSkill(skillId: string): Promise<SkillDetail | null> {
  const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`);
  if (!res.ok) return null;
  return res.json();
}

// Returns the created skill, or an error message string for 409/422s.
export async function installSkill(
  body: string,
  tier: "user" | "org"
): Promise<SkillSummary | string> {
  const res = await fetch(`${API_BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, tier }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) return data?.error ?? `install failed: ${res.status}`;
  return data as SkillSummary;
}

export async function patchSkill(
  skillId: string,
  patch: { enabled?: boolean; trust_state?: "trusted" | "untrusted" }
): Promise<boolean> {
  const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return res.ok;
}

export async function deleteSkill(skillId: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  });
  return res.ok;
}

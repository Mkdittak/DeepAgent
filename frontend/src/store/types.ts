// v1 event envelope (mirrors backend _v1_envelope) and derived UI models.

export type Todo = {
  content: string;
  status: "pending" | "in_progress" | "completed";
};

export interface EnvelopeBase {
  v: 1;
  run_id: string;
  offset: number;
  ts: string;
  user_id: string | null;
  org_id: string | null;
}

export type V1Event = EnvelopeBase &
  (
    | { type: "run.started"; prompt: string }
    | { type: "text.delta"; text: string }
    | { type: "tool.started"; step_id: string; name: string; args: unknown }
    | { type: "tool.progress"; step_id: string; tool: string; message: string }
    | {
        type: "tool.finished";
        step_id: string;
        name: string;
        status: string;
        output_preview?: string;
        duration_ms?: number;
      }
    | { type: "plan.snapshot"; todos: Todo[] }
    | { type: "file.created"; filename: string; url: string }
    | { type: "run.error"; message: string }
    | {
        type: "run.finished";
        state: "done" | "cancelled" | "error";
        summary?: string;
        artifacts?: string[];
      }
  );

// ---- Derived UI blocks / turns / runs ----

export type Block =
  | { kind: "text"; id: string; text: string }
  | {
      kind: "tool";
      id: string;
      stepId: string;
      name: string;
      args: unknown;
      status: "running" | "done" | "error";
      progress: string[];
      output?: string;
      durationMs?: number;
    }
  | { kind: "plan"; id: string; todos: Todo[] }
  | { kind: "artifact"; id: string; filename: string; url: string }
  | { kind: "error"; id: string; message: string };

export type RunState = "streaming" | "done" | "cancelled" | "error";

export type Turn =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; blocks: Block[]; state: RunState };

export interface Run {
  runId: string;
  turns: Turn[];
  state: RunState;
  lastOffset: number;
  seenOffsets: Set<number>;
}

export interface RunSummary {
  run_id: string;
  workflow_id: string;
  artifacts: string[];
  user_message?: string;
  status?: string;
  mtime?: number; // epoch seconds (dir mtime); 0 when unknown
}

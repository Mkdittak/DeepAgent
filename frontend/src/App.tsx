import { useState, useRef, useEffect, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types: Turn / Block model
// ---------------------------------------------------------------------------

type Block =
  | { kind: "text"; text: string }
  | {
      kind: "tool";
      id: string;
      name: string;
      args: unknown;
      status: "running" | "done" | "error";
      progress: string[];
      output?: string;
      durationMs?: number;
    }
  | { kind: "artifact"; filename: string; runId: string }
  | { kind: "plan"; text: string }
  | { kind: "error"; message: string };

type Turn =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      blocks: Block[];
      state: "streaming" | "done" | "cancelled" | "error";
    };

interface RunInfo {
  run_id: string;
  workflow_id: string;
  artifacts: string[];
  user_message?: string;
  status?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WS_URL = `ws://${window.location.hostname}:8000/ws/chat`;
const API_URL = `http://${window.location.hostname}:8000`;

const EXAMPLE_PROMPTS = [
  "Research the latest AI trends and summarize them",
  "Search for Amazon market data and create a report",
  "Find the top 10 most popular programming languages in 2025",
];

// ---------------------------------------------------------------------------
// Reducer: event → Turn[] mutation
// ---------------------------------------------------------------------------

function reduceEvent(
  turns: Turn[],
  data: Record<string, unknown>,
  seenSeqs: Set<number>
): Turn[] {
  const eventType = (data.event_type || data.step || "") as string;
  const seq = (data.seq ?? -1) as number;

  // Idempotent by seq
  if (seq >= 0 && seenSeqs.has(seq)) return turns;
  if (seq >= 0) seenSeqs.add(seq);

  // Deep-clone turns so React sees new references on every mutation
  const next = turns.map((t) =>
    t.role === "assistant"
      ? { ...t, blocks: t.blocks.map((b) => ({ ...b })) as Block[] }
      : { ...t }
  ) as Turn[];

  // Get or create the current assistant turn
  const ensureAssistant = (): Turn & { role: "assistant" } => {
    const last = next[next.length - 1];
    if (last && last.role === "assistant") return last;
    const turn: Turn = { role: "assistant", blocks: [], state: "streaming" };
    next.push(turn);
    return turn as Turn & { role: "assistant" };
  };

  // Handle status messages (non-progress)
  if ((data.type as string) === "status") {
    return turns; // no change — return original reference so React skips render
  }

  // Handle bare error messages (non-progress)
  if ((data.type as string) === "error" && !eventType) {
    const asst = ensureAssistant();
    asst.blocks = [
      ...asst.blocks,
      { kind: "error", message: (data.detail as string) || "Unknown error" },
    ];
    asst.state = "error";
    return next;
  }

  switch (eventType) {
    case "run_start": {
      const userMessage = (data.label as string) || "";
      if (userMessage) {
        const hasUser = next.some(
          (t) => t.role === "user" && t.text === userMessage
        );
        if (!hasUser) {
          next.push({ role: "user", text: userMessage });
        }
      }
      next.push({ role: "assistant", blocks: [], state: "streaming" });
      break;
    }

    case "llm_token": {
      const asst = ensureAssistant();
      const tokenText = (data.label as string) || "";
      const lastIdx = asst.blocks.length - 1;
      const lastBlock = asst.blocks[lastIdx];
      if (lastBlock && lastBlock.kind === "text") {
        // Replace with a NEW object so React sees the change
        asst.blocks[lastIdx] = { kind: "text", text: lastBlock.text + tokenText };
      } else {
        asst.blocks = [...asst.blocks, { kind: "text", text: tokenText }];
      }
      break;
    }

    case "tool_start": {
      const asst = ensureAssistant();
      asst.blocks = [
        ...asst.blocks,
        {
          kind: "tool",
          id: (data.step_id as string) || "",
          name: (data.tool as string) || "unknown",
          args: data.args ?? null,
          status: "running",
          progress: [],
        },
      ];
      break;
    }

    case "tool_progress": {
      const asst = ensureAssistant();
      const stepId = data.step_id as string;
      asst.blocks = asst.blocks.map((b) =>
        b.kind === "tool" && b.id === stepId
          ? { ...b, progress: [...(b as Block & { kind: "tool" }).progress, (data.label as string) || ""] }
          : b
      );
      break;
    }

    case "tool_end": {
      const asst = ensureAssistant();
      const stepId = data.step_id as string;
      asst.blocks = asst.blocks.map((b) =>
        b.kind === "tool" && b.id === stepId
          ? {
              ...b,
              status: "done" as const,
              output: (data.output_preview as string) || undefined,
              durationMs: (data.duration_ms as number) || undefined,
            }
          : b
      );
      break;
    }

    case "artifact": {
      const asst = ensureAssistant();
      const artifacts = (data.artifacts as string[]) || [];
      const rid = (data.run_id as string) || "";
      asst.blocks = [
        ...asst.blocks,
        ...artifacts.map((fname) => ({ kind: "artifact" as const, filename: fname, runId: rid })),
      ];
      break;
    }

    case "error": {
      const asst = ensureAssistant();
      asst.blocks = [
        ...asst.blocks,
        { kind: "error", message: (data.label as string) || "Unknown error" },
      ];
      asst.state = "error";
      break;
    }

    case "done": {
      const asst = ensureAssistant();
      asst.state = "done";
      const artifacts = (data.artifacts as string[]) || [];
      const rid = (data.run_id as string) || "";
      const newArtifacts = artifacts.filter(
        (fname) => !asst.blocks.some((b) => b.kind === "artifact" && b.filename === fname)
      );
      if (newArtifacts.length > 0) {
        asst.blocks = [
          ...asst.blocks,
          ...newArtifacts.map((fname) => ({ kind: "artifact" as const, filename: fname, runId: rid })),
        ];
      }
      break;
    }

    case "cancelled":
    case "cancel_requested": {
      if (eventType === "cancelled") {
        const asst = ensureAssistant();
        asst.state = "cancelled";
      }
      break;
    }

    case "plan": {
      const asst = ensureAssistant();
      const planText = (data.label as string) || "Updating plan...";
      // Merge into the last plan block if one exists — don't spam separate blocks
      const lastBlock = asst.blocks[asst.blocks.length - 1];
      if (lastBlock && lastBlock.kind === "plan") {
        asst.blocks = [
          ...asst.blocks.slice(0, -1),
          { kind: "plan" as const, text: planText },
        ];
      } else {
        asst.blocks = [...asst.blocks, { kind: "plan" as const, text: planText }];
      }
      break;
    }

    default:
      break;
  }

  return next;
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function renderTextBlock(block: Block & { kind: "text" }, isStreaming: boolean) {
  return (
    <span className="text-block">
      {block.text}
      {isStreaming && <span className="cursor">▋</span>}
    </span>
  );
}

/** Turn a progress line like "Read: Title — https://example.com" into JSX with a clickable link */
function renderProgressLine(line: string) {
  const urlMatch = line.match(/(https?:\/\/[^\s]+)/);
  if (!urlMatch) return line;

  const url = urlMatch[1];
  const idx = line.indexOf(url);
  const before = line.slice(0, idx);
  const after = line.slice(idx + url.length);
  // Show a clean domain instead of the full URL
  let domain = "";
  try { domain = new URL(url).hostname.replace(/^www\./, ""); } catch { domain = url; }

  return (
    <>
      {before}
      <a href={url} target="_blank" rel="noopener noreferrer" className="progress-link">{domain}</a>
      {after}
    </>
  );
}

function renderToolBlock(block: Block & { kind: "tool" }) {
  const hasProgress = block.progress.length > 0;

  return (
    <div className={`tool-block ${block.status === "done" ? "tool-done" : ""}`}>
      <div className="tool-header">
        {block.status === "running" && <span className="tool-spinner" />}
        <span className="tool-name">{block.name}</span>
        {block.status === "done" && block.durationMs != null && (
          <span className="tool-duration"> · {formatDuration(block.durationMs)}</span>
        )}
      </div>
      {hasProgress && (
        <div className="tool-progress-list">
          {block.progress.map((line, i) => (
            <div key={i} className="tool-progress-item">{renderProgressLine(line)}</div>
          ))}
        </div>
      )}
      {block.status === "done" && block.output && (
        <details className="tool-output-details">
          <summary className="tool-output-summary">Output</summary>
          <pre className="tool-output-content">{block.output}</pre>
        </details>
      )}
    </div>
  );
}

function getFileExt(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function fileTypeLabel(ext: string): string {
  switch (ext) {
    case ".pptx": return "PowerPoint";
    case ".xlsx": return "Excel Spreadsheet";
    case ".docx": return "Word Document";
    case ".pdf":  return "PDF Document";
    case ".html": return "HTML";
    case ".csv":  return "CSV";
    case ".json": return "JSON";
    case ".zip":  return "ZIP Archive";
    default:      return "File";
  }
}

function renderArtifactBlock(block: Block & { kind: "artifact" }) {
  const url = `${API_URL}/artifacts/${block.runId}/${block.filename}`;
  const ext = getFileExt(block.filename);

  // HTML files: render inline in a sandboxed iframe
  if (ext === ".html" || ext === ".htm") {
    return (
      <div className="artifact-block">
        <div className="artifact-iframe-wrapper">
          <iframe
            src={url}
            sandbox="allow-scripts"
            className="artifact-iframe"
            title={block.filename}
          />
        </div>
        <div className="artifact-card-footer">
          <span className="artifact-filename">{block.filename}</span>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="artifact-open-btn"
          >
            Open full page
          </a>
        </div>
      </div>
    );
  }

  // All other files: preview card with download
  return (
    <div className="artifact-block">
      <div className="artifact-card">
        <div className="artifact-card-icon">{ext === ".pptx" ? "\u{1F4CA}" : ext === ".xlsx" ? "\u{1F4C8}" : "\u{1F4C4}"}</div>
        <div className="artifact-card-info">
          <span className="artifact-filename">{block.filename}</span>
          <span className="artifact-type-label">{fileTypeLabel(ext)}</span>
        </div>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="artifact-download-btn"
        >
          Download
        </a>
      </div>
    </div>
  );
}

function renderPlanBlock(block: Block & { kind: "plan" }) {
  return (
    <div className="plan-block">
      <div className="plan-header">Plan</div>
      <pre className="plan-content">{block.text}</pre>
    </div>
  );
}

function renderErrorBlock(block: Block & { kind: "error" }) {
  return <div className="error-block">{block.message}</div>;
}

function renderBlock(block: Block, isStreaming: boolean) {
  switch (block.kind) {
    case "text":
      return renderTextBlock(block, isStreaming);
    case "tool":
      return renderToolBlock(block);
    case "artifact":
      return renderArtifactBlock(block);
    case "plan":
      return renderPlanBlock(block);
    case "error":
      return renderErrorBlock(block);
  }
}

function renderTurn(turn: Turn, index: number) {
  if (turn.role === "user") {
    return (
      <div key={index} className="turn turn-user">
        <div className="user-bubble">{turn.text}</div>
      </div>
    );
  }

  // Assistant turn
  const isStreaming = turn.state === "streaming";
  // Check if the last block is a text block — the cursor attaches there
  const lastBlockIndex = turn.blocks.length - 1;

  return (
    <div key={index} className="turn turn-assistant">
      {turn.blocks.map((block, bi) => {
        const isLastText =
          isStreaming && bi === lastBlockIndex && block.kind === "text";
        return (
          <div key={bi} className="block">
            {renderBlock(block, isLastText)}
          </div>
        );
      })}
      {/* If streaming but no text block at end (e.g. after a tool block), show standalone cursor */}
      {isStreaming &&
        (turn.blocks.length === 0 ||
          turn.blocks[lastBlockIndex]?.kind !== "text") && (
          <div className="block">
            <span className="text-block">
              <span className="cursor">▋</span>
            </span>
          </div>
        )}
      {turn.state === "cancelled" && (
        <div className="block">
          <div className="cancelled-label">Cancelled</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function App() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [pastRuns, setPastRuns] = useState<RunInfo[]>([]);
  const [showRuns, setShowRuns] = useState(false);
  const [showJump, setShowJump] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const seenSeqs = useRef(new Set<number>());
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isNearBottom = useRef(true);

  // --- Scroll logic ---
  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const threshold = 100;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    isNearBottom.current = nearBottom;
    setShowJump(!nearBottom);
  }, []);

  const jumpToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // Auto-scroll when turns change, but only if near bottom
  useEffect(() => {
    if (isNearBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    } else {
      // Show jump pill when new content arrives while scrolled up
      setShowJump(true);
    }
  }, [turns]);

  // --- Past runs ---
  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/runs`);
      const data: RunInfo[] = await res.json();
      setPastRuns(data);
    } catch {
      // backend may not be up yet
    }
  }, []);

  // --- WebSocket connection ---
  const connect = useCallback(
    (message: string, existingRunId?: string) => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setRunning(true);
        setStopping(false);
        ws.send(
          JSON.stringify({
            type: "start",
            message,
            run_id: existingRunId || undefined,
          })
        );
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // Capture run_id
        if (data.run_id && !runId) {
          setRunId(data.run_id);
          localStorage.setItem("deepagent_run_id", data.run_id);
        }

        setTurns((prev) => reduceEvent(prev, data, seenSeqs.current));

        // Terminal events
        const eventType = (data.event_type || "") as string;
        if (
          eventType === "done" ||
          eventType === "cancelled" ||
          eventType === "error"
        ) {
          // Clear the force-close timer if cancel completed naturally
          if (cancelTimer.current) {
            clearTimeout(cancelTimer.current);
            cancelTimer.current = null;
          }
          setRunning(false);
          setStopping(false);
          localStorage.removeItem("deepagent_run_id");
          fetchRuns();
        }
      };

      ws.onclose = () => {
        if (cancelTimer.current) {
          clearTimeout(cancelTimer.current);
          cancelTimer.current = null;
        }
        setConnected(false);
        setRunning(false);
        setStopping(false);
      };
      ws.onerror = () => {
        if (cancelTimer.current) {
          clearTimeout(cancelTimer.current);
          cancelTimer.current = null;
        }
        setConnected(false);
        setRunning(false);
        setStopping(false);
      };
    },
    [runId, fetchRuns]
  );

  // Reconnect to in-progress run on mount
  useEffect(() => {
    const savedRunId = localStorage.getItem("deepagent_run_id");
    if (savedRunId) {
      connect("", savedRunId);
    }
  }, [connect]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // --- Handlers ---
  const handleSend = () => {
    const text = input.trim();
    if (!text || running) return;

    setTurns([]);
    seenSeqs.current.clear();
    setInput("");
    setRunId(null);
    connect(text);
  };

  const cancelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleStop = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "cancel" }));
      setStopping(true);

      // Force-close after 5s if the backend doesn't send a terminal event
      cancelTimer.current = setTimeout(() => {
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
        setRunning(false);
        setStopping(false);
        setConnected(false);
        localStorage.removeItem("deepagent_run_id");
        // Mark the assistant turn as cancelled
        setTurns((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === "assistant") {
            next[next.length - 1] = { ...last, state: "cancelled" };
          }
          return next;
        });
      }, 5000);
    }
  };

  const handleReconnect = async (rid: string) => {
    setShowRuns(false);
    setRunId(rid);
    seenSeqs.current.clear();

    // Load saved events from backend and replay them
    try {
      const res = await fetch(`${API_URL}/runs/${rid}/events`);
      if (res.ok) {
        const events: Record<string, unknown>[] = await res.json();
        if (events.length > 0) {
          let rebuilt: Turn[] = [];
          for (const ev of events) {
            rebuilt = reduceEvent(rebuilt, ev, seenSeqs.current);
          }
          // Mark the last assistant turn as done (it's a finished run)
          const last = rebuilt[rebuilt.length - 1];
          if (last && last.role === "assistant" && (last as Turn & { role: "assistant" }).state === "streaming") {
            (last as Turn & { role: "assistant" }).state = "done";
          }
          setTurns(rebuilt);
          setRunning(false);
          return;
        }
      }
    } catch {
      // Fallback: try live reconnect
    }

    // If no saved events, try live reconnect (run might still be in progress)
    setTurns([]);
    connect("", rid);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
  };

  const handleExampleClick = (prompt: string) => {
    setInput(prompt);
    // Focus the textarea so user can edit or just hit Enter
    textareaRef.current?.focus();
  };

  const isEmpty = turns.length === 0 && !running;

  return (
    <>
      <style>{CSS}</style>
      <div className="app">
        {/* Header */}
        <div className="header">
          <div className="header-left">
            <h1 className="title">DeepAgent</h1>
            {connected && <span className="connected-dot" />}
          </div>
          <button
            className="runs-button"
            onClick={() => {
              setShowRuns(!showRuns);
              if (!showRuns) fetchRuns();
            }}
          >
            {showRuns ? "Hide Runs" : "Past Runs"}
            {pastRuns.length > 0 && (
              <span className="runs-badge">{pastRuns.length}</span>
            )}
          </button>
        </div>

        {/* Past runs panel */}
        {showRuns && (
          <div className="runs-panel">
            {pastRuns.length === 0 ? (
              <p className="no-runs">No runs yet.</p>
            ) : (
              pastRuns.map((run) => (
                <div key={run.run_id} className="run-item">
                  <div className="run-info">
                    <span className="run-message">
                      {run.user_message || run.run_id}
                    </span>
                    <span className="run-meta">
                      {run.status && run.status !== "unknown" && (
                        <span className={`run-status run-status-${run.status}`}>
                          {run.status}
                        </span>
                      )}
                      {run.artifacts.length > 0 && (
                        <span className="artifact-count">
                          {run.artifacts.length} file
                          {run.artifacts.length !== 1 ? "s" : ""}
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="run-actions">
                    <button
                      className="reconnect-btn"
                      onClick={() => handleReconnect(run.run_id)}
                      disabled={running}
                    >
                      Reconnect
                    </button>
                    {run.artifacts.map((f) => {
                      const isHtml = f.endsWith(".html") || f.endsWith(".htm");
                      return (
                        <a
                          key={f}
                          href={`${API_URL}/artifacts/${run.run_id}/${f}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={isHtml ? "open-link" : "dl-link"}
                        >
                          {isHtml ? "Open" : f}
                        </a>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Conversation area */}
        <div className="conversation" ref={scrollRef} onScroll={checkScroll}>
          {isEmpty ? (
            <div className="empty-state">
              <h2 className="empty-title">DeepAgent</h2>
              <p className="empty-desc">
                General-purpose autonomous agent. Ask anything.
              </p>
              <div className="examples">
                {EXAMPLE_PROMPTS.map((prompt, i) => (
                  <button
                    key={i}
                    className="example-btn"
                    onClick={() => handleExampleClick(prompt)}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((turn, i) => renderTurn(turn, i))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Jump to latest pill */}
        {showJump && !isEmpty && (
          <button className="jump-pill" onClick={jumpToBottom}>
            ↓ Jump to latest
          </button>
        )}

        {/* Input area */}
        <div className="input-area">
          <textarea
            ref={textareaRef}
            className="input-field"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask DeepAgent anything..."
            rows={1}
            disabled={running}
          />
          <div className="input-actions">
            {running ? (
              <button
                className="action-btn stop-btn"
                onClick={handleStop}
                disabled={stopping}
              >
                {stopping ? "Stopping..." : "Stop"}
              </button>
            ) : (
              <button
                className="action-btn send-btn"
                onClick={handleSend}
                disabled={!input.trim()}
              >
                Send
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const CSS = `
/* Reset & base */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 720px;
  margin: 0 auto;
  padding: 0 24px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 15px;
  line-height: 1.65;
  color: #1a1a1a;
  background: #ffffff;
}

/* Header */
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0 12px;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.connected-dot {
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  flex-shrink: 0;
}

.runs-button {
  padding: 6px 14px;
  font-size: 13px;
  background: #f5f5f4;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #1a1a1a;
  font-family: inherit;
}

.runs-button:hover { background: #ececeb; }

.runs-badge {
  background: #2563eb;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
}

/* Past runs panel */
.runs-panel {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  margin-top: 8px;
  background: #fafaf9;
  max-height: 180px;
  overflow-y: auto;
  flex-shrink: 0;
}

.no-runs { color: #6b7280; font-size: 13px; }

.run-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.run-item:last-child { border-bottom: none; }

.run-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.run-message {
  font-size: 13px;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.run-status {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.run-status-done { color: #16a34a; background: #f0fdf4; }
.run-status-running { color: #d97706; background: #fffbeb; }
.run-status-error { color: #dc2626; background: #fef2f2; }
.run-status-cancelled { color: #6b7280; background: #f3f4f6; }

.artifact-count {
  font-size: 11px;
  color: #16a34a;
  background: #f0fdf4;
  padding: 1px 6px;
  border-radius: 4px;
}

.run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
}

.reconnect-btn {
  padding: 3px 10px;
  font-size: 12px;
  background: #fff;
  border: 1px solid #2563eb;
  color: #2563eb;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
}

.reconnect-btn:hover { background: #eff6ff; }
.reconnect-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.dl-link {
  display: inline-block;
  padding: 3px 10px;
  background: #2563eb;
  color: #fff;
  border-radius: 4px;
  text-decoration: none;
  font-size: 12px;
}

.dl-link:hover { background: #1d4ed8; }

.open-link {
  display: inline-block;
  padding: 3px 10px;
  background: #16a34a;
  color: #fff;
  border-radius: 4px;
  text-decoration: none;
  font-size: 12px;
}

.open-link:hover { background: #15803d; }

/* Conversation */
.conversation {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* Turns */
.turn { display: flex; flex-direction: column; gap: 8px; }

.turn-user {
  align-items: flex-start;
}

.user-bubble {
  background: #f5f5f4;
  border-radius: 12px;
  padding: 12px 16px;
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 85%;
  font-size: 15px;
  line-height: 1.6;
}

.turn-assistant {
  align-items: flex-start;
  padding: 4px 0;
}

/* Blocks */
.block { width: 100%; }

.text-block {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.75;
  color: #1a1a1a;
  letter-spacing: 0.01em;
}

.cursor {
  display: inline;
  animation: blink 1s step-end infinite;
  color: #2563eb;
  font-weight: 600;
  font-size: 16px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.tool-block {
  font-size: 13px;
  color: #6b7280;
  padding: 8px 12px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  margin: 4px 0;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-name { font-weight: 500; color: #374151; }

.tool-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid #e5e7eb;
  border-top-color: #6b7280;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.tool-done { border-color: #f0f0f0; }

.tool-duration { color: #9ca3af; }

.tool-progress-list {
  margin-top: 6px;
  padding-left: 20px;
  border-left: 2px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.tool-progress-item {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  word-break: break-word;
}

.progress-link {
  color: #2563eb;
  text-decoration: none;
}

.progress-link:hover {
  text-decoration: underline;
}

.tool-output-details {
  margin-top: 6px;
  cursor: pointer;
}

.tool-output-summary {
  font-size: 12px;
  color: #9ca3af;
  font-weight: 500;
}

.tool-output-content {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  color: #4b5563;
  max-height: 200px;
  overflow-y: auto;
  background: #f3f4f6;
  padding: 8px;
  border-radius: 4px;
}

/* Artifact blocks */
.artifact-block {
  padding: 4px 0;
}

.artifact-iframe-wrapper {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}

.artifact-iframe {
  display: block;
  width: 100%;
  height: 400px;
  border: none;
}

.artifact-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-top: none;
  border-radius: 0 0 10px 10px;
  margin-top: -1px;
}

.artifact-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.artifact-card-icon {
  font-size: 24px;
  flex-shrink: 0;
  line-height: 1;
}

.artifact-card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.artifact-filename {
  font-size: 14px;
  font-weight: 500;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-type-label {
  font-size: 12px;
  color: #6b7280;
}

.artifact-open-btn {
  font-size: 13px;
  color: #2563eb;
  text-decoration: none;
  white-space: nowrap;
}

.artifact-open-btn:hover { text-decoration: underline; }

.artifact-download-btn {
  padding: 6px 14px;
  font-size: 13px;
  background: #2563eb;
  color: #fff;
  border-radius: 6px;
  text-decoration: none;
  white-space: nowrap;
  flex-shrink: 0;
}

.artifact-download-btn:hover { background: #1d4ed8; }

/* Plan blocks */
.plan-block {
  font-size: 13px;
  padding: 10px 14px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  margin: 4px 0;
}

.plan-header {
  font-weight: 600;
  color: #0369a1;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.plan-content {
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1e3a5f;
  max-height: 250px;
  overflow-y: auto;
  margin: 0;
  font-family: inherit;
}

.error-block {
  color: #dc2626;
  font-size: 14px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  margin: 4px 0;
}

.cancelled-label {
  color: #6b7280;
  font-size: 13px;
  font-style: italic;
  padding: 4px 0;
}

/* Empty state */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
  text-align: center;
}

.empty-title {
  font-size: 28px;
  font-weight: 600;
  color: #1a1a1a;
  letter-spacing: -0.02em;
}

.empty-desc {
  color: #6b7280;
  font-size: 15px;
  margin-bottom: 12px;
}

.examples {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 400px;
}

.example-btn {
  padding: 10px 16px;
  font-size: 14px;
  color: #374151;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  line-height: 1.4;
  transition: background 0.15s, border-color 0.15s;
}

.example-btn:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

/* Jump pill */
.jump-pill {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 100px;
  padding: 6px 16px;
  font-size: 13px;
  font-family: inherit;
  background: #1a1a1a;
  color: #fff;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  z-index: 10;
  transition: opacity 0.15s;
}

.jump-pill:hover { background: #333; }

/* Input area */
.input-area {
  display: flex;
  gap: 8px;
  padding: 12px 0 16px;
  border-top: 1px solid #e5e7eb;
  flex-shrink: 0;
  align-items: flex-end;
}

.input-field {
  flex: 1;
  padding: 10px 14px;
  font-size: 15px;
  font-family: inherit;
  line-height: 1.5;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  resize: none;
  outline: none;
  min-height: 42px;
  max-height: 140px;
  background: #fff;
  color: #1a1a1a;
  transition: border-color 0.15s;
}

.input-field:focus { border-color: #2563eb; }
.input-field:disabled { background: #f9fafb; color: #9ca3af; }

.input-actions {
  flex-shrink: 0;
}

.action-btn {
  padding: 10px 24px;
  font-size: 15px;
  font-family: inherit;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  font-weight: 500;
  min-width: 90px;
  height: 42px;
  transition: background 0.15s;
}

.send-btn {
  background: #2563eb;
  color: #fff;
}

.send-btn:hover { background: #1d4ed8; }
.send-btn:disabled { background: #93c5fd; cursor: not-allowed; }

.stop-btn {
  background: #dc2626;
  color: #fff;
}

.stop-btn:hover { background: #b91c1c; }
.stop-btn:disabled { background: #999; cursor: not-allowed; }

/* Scrollbar */
.conversation::-webkit-scrollbar { width: 6px; }
.conversation::-webkit-scrollbar-track { background: transparent; }
.conversation::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
.conversation::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

/* Global body fix */
body { margin: 0; background: #ffffff; }
`;

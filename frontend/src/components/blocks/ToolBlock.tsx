import { memo, useState } from "react";
import type { Block } from "../../store/types";
import "./ToolBlock.css";

type Props = { block: Extract<Block, { kind: "tool" }> };

function fmtDuration(ms?: number): string {
  if (ms == null) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function argsPreview(args: unknown): string {
  if (args == null) return "";
  try {
    const s = typeof args === "string" ? args : JSON.stringify(args);
    return s.length > 300 ? s.slice(0, 300) + "…" : s;
  } catch {
    return String(args);
  }
}

function linkify(line: string) {
  const m = line.match(/(https?:\/\/[^\s]+)/);
  if (!m) return line;
  const url = m[1];
  const i = line.indexOf(url);
  let host = url;
  try {
    host = new URL(url).hostname.replace(/^www\./, "");
  } catch {
    /* keep raw */
  }
  return (
    <>
      {line.slice(0, i)}
      <a href={url} target="_blank" rel="noopener noreferrer">{host}</a>
      {line.slice(i + url.length)}
    </>
  );
}

function ToolBlockImpl({ block }: Props) {
  const [open, setOpen] = useState(false);
  const args = argsPreview(block.args);
  return (
    <div className={`da-tool ${block.status === "done" ? "is-done" : ""}`}>
      <div className="da-tool-head">
        {block.status === "running" && <span className="da-spinner" aria-hidden />}
        <span className="da-tool-name">{block.name}</span>
        {block.status === "done" && block.durationMs != null && (
          <span className="da-tool-dur">· {fmtDuration(block.durationMs)}</span>
        )}
        <span className={`da-tool-status da-status-${block.status}`}>{block.status}</span>
      </div>
      {args && <div className="da-tool-args"><code>{args}</code></div>}
      {block.progress.length > 0 && (
        <div className="da-tool-progress">
          {block.progress.map((line, i) => (
            <div key={i} className="da-tool-progress-line">{linkify(line)}</div>
          ))}
        </div>
      )}
      {block.output && (
        <div className="da-tool-output">
          <button className="da-tool-output-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? "Hide output" : "Show output"}
          </button>
          {open && <pre className="da-tool-output-body">{block.output}</pre>}
        </div>
      )}
    </div>
  );
}

export const ToolBlock = memo(ToolBlockImpl);

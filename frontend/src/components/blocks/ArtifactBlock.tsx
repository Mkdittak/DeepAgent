import { memo, useEffect, useRef, useState } from "react";
import type { Block } from "../../store/types";
import { API_BASE } from "../../net/api";
import "./ArtifactBlock.css";

type Props = { block: Extract<Block, { kind: "artifact" }> };

function ext(name: string): string {
  const d = name.lastIndexOf(".");
  return d >= 0 ? name.slice(d).toLowerCase() : "";
}

const LABEL: Record<string, string> = {
  ".pptx": "PowerPoint",
  ".xlsx": "Excel Spreadsheet",
  ".docx": "Word Document",
  ".pdf": "PDF",
  ".html": "HTML Page",
  ".htm": "HTML Page",
  ".csv": "CSV",
  ".json": "JSON",
};

const ICON: Record<string, string> = {
  ".pptx": "📊",
  ".xlsx": "📈",
  ".html": "🌐",
  ".htm": "🌐",
  ".pdf": "📄",
};

// url may be relative (from file.created) or absolute — normalize against API.
function fullUrl(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}

function ArtifactBlockImpl({ block }: Props) {
  const e = ext(block.filename);
  const url = fullUrl(block.url);
  const isHtml = e === ".html" || e === ".htm";

  const [expanded, setExpanded] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!expanded) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // lock body scroll behind the overlay
    closeRef.current?.focus(); // move focus to Close on open
    // Escape is a bonus: once focus is inside the iframe it won't reach here.
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow; // restore scroll
      triggerRef.current?.focus(); // return focus to the trigger
    };
  }, [expanded]);

  return (
    <div className="da-artifact">
      {isHtml && (
        <button
          className="da-artifact-preview"
          ref={triggerRef}
          onClick={() => setExpanded(true)}
          aria-label={`Expand ${block.filename}`}
        >
          {/* Sandboxed: allow-scripts only (NO allow-same-origin). Inline iframe
              is a non-interactive preview (pointer-events off) — click to expand. */}
          <iframe src={url} sandbox="allow-scripts" title={block.filename} tabIndex={-1} />
          <span className="da-artifact-expand-hint">⤢ Click to expand</span>
        </button>
      )}
      <div className="da-artifact-card">
        <span className="da-artifact-icon">{ICON[e] ?? "📄"}</span>
        <span className="da-artifact-info">
          <span className="da-artifact-name">{block.filename}</span>
          <span className="da-artifact-type">{LABEL[e] ?? "File"}</span>
        </span>
        {isHtml && (
          <button className="da-artifact-expand-btn" onClick={() => setExpanded(true)}>
            Expand
          </button>
        )}
        <a className="da-artifact-dl" href={url} download target="_blank" rel="noopener noreferrer">
          Download
        </a>
      </div>

      {expanded && (
        // Backdrop: clicking outside the panel closes.
        <div className="da-overlay" onClick={() => setExpanded(false)}>
          <div className="da-overlay-panel" onClick={(ev) => ev.stopPropagation()}>
            <div className="da-overlay-head">
              <span className="da-overlay-name">{block.filename}</span>
              <a className="da-overlay-dl" href={url} download target="_blank" rel="noopener noreferrer">
                Download
              </a>
              <button ref={closeRef} className="da-overlay-close" onClick={() => setExpanded(false)}>
                ✕ Close
              </button>
            </div>
            {/* Same sandbox as inline — allow-scripts, NO allow-same-origin. */}
            <iframe
              className="da-overlay-iframe"
              src={url}
              sandbox="allow-scripts"
              title={block.filename}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export const ArtifactBlock = memo(ArtifactBlockImpl);

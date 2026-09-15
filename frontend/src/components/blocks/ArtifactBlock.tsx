import { memo, useEffect, useRef, useState } from "react";
import type { Block } from "../../store/types";
import { signArtifactUrl } from "../../net/api";
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

// block.url is "/artifacts/<run_id>/<filename>" (relative, from file.created
// or the run.finished artifacts list) or an absolute form of the same path.
// The run_id + filename pair is what the signing endpoint takes.
const ARTIFACT_PATH = /\/artifacts\/([^/?#]+)\/([^/?#]+)/;
function parseArtifact(url: string, fallbackName: string): { runId: string; filename: string } | null {
  const m = ARTIFACT_PATH.exec(url);
  if (!m) return null;
  try {
    return { runId: decodeURIComponent(m[1]), filename: decodeURIComponent(m[2]) || fallbackName };
  } catch {
    return null;
  }
}

// ?download=1 forces Content-Disposition: attachment so an .html artifact
// downloads instead of rendering top-level at the API origin. Signed URLs
// already carry a query string, so append with the right separator.
function withDownload(url: string): string {
  return `${url}${url.includes("?") ? "&" : "?"}download=1`;
}

// Fetch a (signed) URL whenever `active` becomes true. Signatures are
// short-lived (~60s), so each consumer — inline preview on mount, overlay on
// expand, download on click — asks for a fresh one at the moment it needs it
// rather than sharing one that may have expired.
function useArtifactUrl(runId: string | null, filename: string | null, active: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!active || !runId || !filename) return;
    let cancelled = false;
    setUrl(null);
    void signArtifactUrl(runId, filename).then((u) => {
      if (!cancelled) setUrl(u);
    });
    return () => {
      cancelled = true;
    };
  }, [runId, filename, active]);
  return active ? url : null;
}

function ArtifactBlockImpl({ block }: Props) {
  const e = ext(block.filename);
  const isHtml = e === ".html" || e === ".htm";
  const ref = parseArtifact(block.url, block.filename);
  const runId = ref?.runId ?? null;
  const filename = ref?.filename ?? null;

  const [expanded, setExpanded] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const previewUrl = useArtifactUrl(runId, filename, isHtml);
  const overlayUrl = useArtifactUrl(runId, filename, isHtml && expanded);

  const download = async () => {
    if (!runId || !filename) return;
    const u = await signArtifactUrl(runId, filename);
    // Content-Disposition: attachment -> the browser saves without leaving
    // the page, so a same-window navigation is the least intrusive trigger.
    if (u) window.location.assign(withDownload(u));
  };

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
          {previewUrl && (
            <iframe src={previewUrl} sandbox="allow-scripts" title={block.filename} tabIndex={-1} />
          )}
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
        <button className="da-artifact-dl" onClick={() => void download()} disabled={!ref}>
          Download
        </button>
      </div>

      {expanded && (
        // Backdrop: clicking outside the panel closes.
        <div className="da-overlay" onClick={() => setExpanded(false)}>
          <div className="da-overlay-panel" onClick={(ev) => ev.stopPropagation()}>
            <div className="da-overlay-head">
              <span className="da-overlay-name">{block.filename}</span>
              <button className="da-overlay-dl" onClick={() => void download()}>
                Download
              </button>
              <button ref={closeRef} className="da-overlay-close" onClick={() => setExpanded(false)}>
                ✕ Close
              </button>
            </div>
            {/* Same sandbox as inline — allow-scripts, NO allow-same-origin. */}
            {overlayUrl && (
              <iframe
                className="da-overlay-iframe"
                src={overlayUrl}
                sandbox="allow-scripts"
                title={block.filename}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export const ArtifactBlock = memo(ArtifactBlockImpl);

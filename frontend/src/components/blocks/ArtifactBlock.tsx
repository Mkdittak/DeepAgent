import { memo } from "react";
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

  return (
    <div className="da-artifact">
      {isHtml && (
        <div className="da-artifact-preview">
          {/* Sandboxed: allow-scripts only (NO allow-same-origin) so model-authored
              scripts run in a null origin and cannot reach the API origin. */}
          <iframe src={url} sandbox="allow-scripts" title={block.filename} />
        </div>
      )}
      <div className="da-artifact-card">
        <span className="da-artifact-icon">{ICON[e] ?? "📄"}</span>
        <span className="da-artifact-info">
          <span className="da-artifact-name">{block.filename}</span>
          <span className="da-artifact-type">{LABEL[e] ?? "File"}</span>
        </span>
        <a className="da-artifact-dl" href={url} download target="_blank" rel="noopener noreferrer">
          Download
        </a>
      </div>
    </div>
  );
}

export const ArtifactBlock = memo(ArtifactBlockImpl);

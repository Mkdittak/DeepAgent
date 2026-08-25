import { useEffect, useState } from "react";
import { listRuns, artifactUrl } from "../net/api";
import { reconnect } from "../net/controller";
import type { RunSummary } from "../store/types";
import "./RunsPanel.css";

type Props = { open: boolean; onCountChange: (n: number) => void };

// run_id is `{slug}_{YYYY-MM-DD}_{HH-MM-SS}`. When there is no stored
// user_message (dir-scan backfill), de-slugify the id into something readable.
function readableLabel(run: RunSummary): string {
  if (run.user_message) return run.user_message;
  const m = run.run_id.match(/^(.*)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$/);
  const slug = m ? m[1] : run.run_id;
  const text = slug.replace(/-/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : run.run_id;
}

function formatDate(run: RunSummary): string {
  const secs = run.mtime && run.mtime > 0 ? run.mtime : null;
  const d = secs ? new Date(secs * 1000) : null;
  if (!d || isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function RunsPanel({ open, onCountChange }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    let alive = true;
    listRuns().then((r) => {
      if (alive) {
        setRuns(r);
        onCountChange(r.length);
      }
    });
    return () => {
      alive = false;
    };
  }, [open, onCountChange]);

  if (!open) return null;

  return (
    <div className="da-runs-panel">
      {runs.length === 0 ? (
        <p className="da-runs-empty">No runs yet.</p>
      ) : (
        runs.map((run) => (
          <div key={run.run_id} className="da-run-item">
            <div className="da-run-meta">
              <span className="da-run-msg">{readableLabel(run)}</span>
              <span className="da-run-tags">
                {formatDate(run) && <span className="da-run-date">{formatDate(run)}</span>}
                {run.status && run.status !== "unknown" && (
                  <span className={`da-run-status da-run-status-${run.status}`}>{run.status}</span>
                )}
                {run.artifacts.length > 0 && (
                  <span className="da-run-files">{run.artifacts.length} file{run.artifacts.length !== 1 ? "s" : ""}</span>
                )}
              </span>
            </div>
            <div className="da-run-actions">
              <button className="da-run-reconnect" onClick={() => reconnect(run.run_id)}>
                Reconnect
              </button>
              {run.artifacts.map((f) => (
                <a key={f} href={artifactUrl(run.run_id, f)} download target="_blank" rel="noopener noreferrer" className="da-run-dl">
                  {f}
                </a>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

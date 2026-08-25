import { useEffect, useState } from "react";
import { listRuns, artifactUrl } from "../net/api";
import { reconnect } from "../net/controller";
import type { RunSummary } from "../store/types";
import "./RunsPanel.css";

type Props = { open: boolean; onCountChange: (n: number) => void };

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
              <span className="da-run-msg">{run.user_message || run.run_id}</span>
              <span className="da-run-tags">
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

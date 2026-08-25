import { useStore } from "../store/store";
import "./Header.css";

type Props = { runsOpen: boolean; onToggleRuns: () => void; pastRunCount: number };

export function Header({ runsOpen, onToggleRuns, pastRunCount }: Props) {
  const connected = useStore((s) => s.connected);
  return (
    <header className="da-header">
      <div className="da-header-left">
        <span className="da-logo">DeepAgent</span>
        <span className={`da-dot ${connected ? "is-on" : ""}`} title={connected ? "connected" : "idle"} />
      </div>
      <button className="da-runs-btn" onClick={onToggleRuns}>
        {runsOpen ? "Hide runs" : "Past runs"}
        {pastRunCount > 0 && <span className="da-runs-badge">{pastRunCount}</span>}
      </button>
    </header>
  );
}

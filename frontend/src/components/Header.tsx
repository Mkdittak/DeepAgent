import { useStore } from "../store/store";
import { AUTH_CONFIGURED } from "../auth/stytch";
import { AccountMenu } from "./AccountMenu";
import "./Header.css";

type Props = { onToggleSidebar: () => void };

export function Header({ onToggleSidebar }: Props) {
  const connected = useStore((s) => s.connected);
  return (
    <header className="da-header">
      <button className="da-menu-btn" onClick={onToggleSidebar} aria-label="Toggle sidebar">
        <span className="da-menu-icon" />
      </button>
      <span className="da-logo">DeepAgent</span>
      <span className={`da-dot ${connected ? "is-on" : ""}`} title={connected ? "connected" : "idle"} />
      <span className="da-header-spacer" />
      {/* AccountMenu uses Stytch hooks, so it only mounts when the provider does. */}
      {AUTH_CONFIGURED && <AccountMenu />}
    </header>
  );
}

import { useCallback, useEffect, useState } from "react";
import { useStytchMemberSession } from "@stytch/react/b2b";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { Conversation } from "./components/Conversation";
import { Composer } from "./components/Composer";
import { SkillsManager } from "./components/SkillsManager";
import { useStore, hydrate } from "./store/store";
import { submit, cancel, resumeOnLoad } from "./net/controller";
import { AUTH_CONFIGURED, getStytchClient } from "./auth/stytch";
import { Authenticate, Login } from "./auth/Login";
import "./styles/global.css";
import "./App.css";

const isMobile = () =>
  typeof window !== "undefined" && window.matchMedia("(max-width: 768px)").matches;

// The pre-auth app, unchanged. Rendered directly when auth is unconfigured,
// or behind the session gate when it is.
function Shell() {
  const [input, setInput] = useState("");
  // Sidebar expanded on desktop, closed (drawer) on mobile by default.
  const [sidebarOpen, setSidebarOpen] = useState(() => !isMobile());
  // No router: the sidebar switches the main pane between chat and the
  // skills manager (same pattern as thread selection).
  const [view, setView] = useState<"chat" | "skills">("chat");

  // Show Stop only while the current run is actively streaming AND connected —
  // keeps the composer consistent with the header dot.
  const running = useStore((s) => {
    const last = s.order[s.order.length - 1];
    return s.connected && !!last && s.runs[last]?.state === "streaming";
  });

  useEffect(() => {
    hydrate();
    resumeOnLoad();
  }, []);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void submit(text);
  }, [input]);

  const handleStop = useCallback(() => {
    void cancel();
  }, []);

  // On mobile, selecting a thread / new chat closes the drawer.
  const onNavigate = useCallback(() => {
    if (isMobile()) setSidebarOpen(false);
  }, []);

  return (
    <div className={`da-shell ${sidebarOpen ? "sidebar-open" : "sidebar-collapsed"}`}>
      <Sidebar open={sidebarOpen} onNavigate={onNavigate} view={view} onSetView={setView} />
      <div className="da-backdrop" onClick={() => setSidebarOpen(false)} />
      <div className="da-main">
        <Header onToggleSidebar={() => setSidebarOpen((o) => !o)} />
        {view === "skills" ? (
          <SkillsManager />
        ) : (
          <>
            <Conversation onPickExample={setInput} />
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={handleSubmit}
              onStop={handleStop}
              running={running}
            />
          </>
        )}
      </div>
    </div>
  );
}

// Session gate. Uses the Stytch hooks, so it only mounts under the provider.
//   /authenticate           -> token-exchange handler (magic link / OAuth return)
//   no member session       -> Discovery login (email magic links + Google)
//   session                 -> the shell
function AuthenticatedApp() {
  const { session, isInitialized } = useStytchMemberSession();
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  // Authenticate() rewrites the URL to "/" via replaceState (no popstate),
  // so re-read the path whenever the session flips.
  useEffect(() => {
    setPath(window.location.pathname);
  }, [session]);

  if (path === "/authenticate" && !session) return <Authenticate />;
  if (!isInitialized) return null; // SDK still hydrating the session from cookies
  if (!session) return <Login />;
  return <Shell />;
}

export default function App() {
  // getStytchClient() is null when the token is unset OR the SDK failed to
  // initialize — both fall through to the no-auth shell rather than crashing.
  return AUTH_CONFIGURED && getStytchClient() ? <AuthenticatedApp /> : <Shell />;
}

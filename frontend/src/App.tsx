import { useCallback, useEffect, useState } from "react";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { Conversation } from "./components/Conversation";
import { Composer } from "./components/Composer";
import { SkillsManager } from "./components/SkillsManager";
import { useStore, hydrate } from "./store/store";
import { submit, cancel, resumeOnLoad } from "./net/controller";
import "./styles/global.css";
import "./App.css";

const isMobile = () =>
  typeof window !== "undefined" && window.matchMedia("(max-width: 768px)").matches;

export default function App() {
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

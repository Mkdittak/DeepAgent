import { useCallback, useEffect, useState } from "react";
import { Header } from "./components/Header";
import { RunsPanel } from "./components/RunsPanel";
import { Conversation } from "./components/Conversation";
import { Composer } from "./components/Composer";
import { useStore, hydrate } from "./store/store";
import { submit, cancel, resumeOnLoad } from "./net/controller";
import "./styles/global.css";
import "./App.css";

export default function App() {
  const [input, setInput] = useState("");
  const [runsOpen, setRunsOpen] = useState(false);
  const [pastRunCount, setPastRunCount] = useState(0);

  // A run is active while any run in the session is still streaming.
  const running = useStore((s) => s.order.some((id) => s.runs[id]?.state === "streaming"));

  // Restore scrollback and resume any run that was mid-stream on last load.
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

  return (
    <div className="da-app">
      <Header
        runsOpen={runsOpen}
        onToggleRuns={() => setRunsOpen((o) => !o)}
        pastRunCount={pastRunCount}
      />
      <RunsPanel open={runsOpen} onCountChange={setPastRunCount} />
      <Conversation onPickExample={setInput} />
      <Composer
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
        onStop={handleStop}
        running={running}
      />
    </div>
  );
}

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

  // Show Stop only while the current run is actively streaming AND a stream is
  // connected. Keying off `connected` (same signal as the header dot) keeps the
  // two consistent and prevents an old run left in "streaming" (a stream that
  // closed without a terminal event) from pinning the composer in Stop.
  const running = useStore((s) => {
    const last = s.order[s.order.length - 1];
    return s.connected && !!last && s.runs[last]?.state === "streaming";
  });

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

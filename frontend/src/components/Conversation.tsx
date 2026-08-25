import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "../store/store";
import { TurnView } from "./TurnView";
import { JumpPill } from "./JumpPill";
import "./Conversation.css";

const EXAMPLES = [
  "Research the latest AI trends and summarize them",
  "Make a PowerPoint on the history of jazz",
  "Build a landing page for a coffee shop",
];

type Props = { onPickExample: (text: string) => void };

export function Conversation({ onPickExample }: Props) {
  const order = useStore((s) => s.order);
  const runs = useStore((s) => s.runs);
  // Scalar that changes on every event, to drive autoscroll.
  const tick = useStore((s) =>
    s.order.reduce((n, id) => {
      const r = s.runs[id];
      return n + (r ? r.turns.length + r.lastOffset : 0);
    }, 0)
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    nearBottom.current = near;
    setShowJump(!near);
  }, []);

  const jump = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowJump(false);
  }, []);

  useEffect(() => {
    if (nearBottom.current) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    else setShowJump(true);
  }, [tick]);

  const isEmpty = order.length === 0;

  return (
    <div className="da-conversation-wrap">
      <div className="da-conversation" ref={scrollRef} onScroll={onScroll}>
        {isEmpty ? (
          <div className="da-empty">
            <h1 className="da-empty-title">DeepAgent</h1>
            <p className="da-empty-sub">A general-purpose autonomous agent. Ask anything.</p>
            <div className="da-examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="da-example" onClick={() => onPickExample(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          order.map((runId) => (
            <Fragment key={runId}>
              {(runs[runId]?.turns ?? []).map((t) => (
                <TurnView key={t.id} turn={t} />
              ))}
            </Fragment>
          ))
        )}
        <div ref={bottomRef} />
      </div>
      <JumpPill visible={showJump && !isEmpty} onClick={jump} />
    </div>
  );
}

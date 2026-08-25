import { memo } from "react";
import type { Block } from "../../store/types";
import "./PlanBlock.css";

type Props = { block: Extract<Block, { kind: "plan" }> };

const ICON: Record<string, string> = {
  completed: "✓",
  in_progress: "◐",
  pending: "○",
};

// Renders the plan snapshot in place — one panel, updated as todos change.
function PlanBlockImpl({ block }: Props) {
  const done = block.todos.filter((t) => t.status === "completed").length;
  return (
    <div className="da-plan">
      <div className="da-plan-head">
        <span className="da-plan-title">Plan</span>
        <span className="da-plan-count">{done}/{block.todos.length}</span>
      </div>
      <ul className="da-plan-list">
        {block.todos.map((t, i) => (
          <li key={i} className={`da-plan-item da-plan-${t.status}`}>
            <span className="da-plan-icon">{ICON[t.status] ?? "○"}</span>
            <span className="da-plan-text">{t.content}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const PlanBlock = memo(PlanBlockImpl);

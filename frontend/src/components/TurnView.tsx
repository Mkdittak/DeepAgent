import { memo } from "react";
import type { Turn } from "../store/types";
import { BlockView } from "./BlockView";
import "./TurnView.css";

type Props = { turn: Turn };

// Memoized by turn reference: only the turn whose object changed re-renders.
function TurnViewImpl({ turn }: Props) {
  if (turn.role === "user") {
    return (
      <div className="da-turn da-turn-user">
        <div className="da-user-bubble">{turn.text}</div>
      </div>
    );
  }

  const streaming = turn.state === "streaming";
  const lastIdx = turn.blocks.length - 1;
  const lastIsText = lastIdx >= 0 && turn.blocks[lastIdx].kind === "text";

  return (
    <div className="da-turn da-turn-assistant">
      {turn.blocks.map((b, i) => (
        <BlockView key={b.id} block={b} streaming={streaming && i === lastIdx && b.kind === "text"} />
      ))}
      {streaming && !lastIsText && <span className="da-cursor da-standalone-cursor" aria-hidden />}
      {turn.state === "cancelled" && <div className="da-cancelled">Cancelled</div>}
    </div>
  );
}

export const TurnView = memo(TurnViewImpl);

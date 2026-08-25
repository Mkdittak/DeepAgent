import { memo } from "react";
import type { Block } from "../../store/types";
import "./ErrorBlock.css";

type Props = { block: Extract<Block, { kind: "error" }> };

function ErrorBlockImpl({ block }: Props) {
  return <div className="da-error">{block.message}</div>;
}

export const ErrorBlock = memo(ErrorBlockImpl);

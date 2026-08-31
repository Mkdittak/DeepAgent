import { memo } from "react";
import type { Block } from "../../store/types";
import "./SkillBlock.css";

type Props = { block: Extract<Block, { kind: "skill" }> };

const TIER_LABEL: Record<string, string> = {
  "built-in": "Built-in",
  org: "Organization",
  user: "Your skill",
};

// Announces a skill activation in the feed: the agent matched the task to a
// skill and read its full instructions (progressive disclosure stage 2).
function SkillBlockImpl({ block }: Props) {
  return (
    <div className="da-skill">
      <div className="da-skill-head">
        <span className="da-skill-title">
          Skill activated · <span className="da-skill-name">{block.name}</span>
        </span>
        <span className="da-skill-tier">{TIER_LABEL[block.tier] ?? block.tier}</span>
      </div>
      {block.description && <div className="da-skill-desc">{block.description}</div>}
    </div>
  );
}

export const SkillBlock = memo(SkillBlockImpl);

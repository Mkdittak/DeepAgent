import { memo } from "react";
import type { Block } from "../store/types";
import { TextBlock } from "./blocks/TextBlock";
import { ToolBlock } from "./blocks/ToolBlock";
import { PlanBlock } from "./blocks/PlanBlock";
import { SkillBlock } from "./blocks/SkillBlock";
import { ArtifactBlock } from "./blocks/ArtifactBlock";
import { ErrorBlock } from "./blocks/ErrorBlock";

type Props = { block: Block; streaming: boolean };

function BlockViewImpl({ block, streaming }: Props) {
  switch (block.kind) {
    case "text":
      return <TextBlock block={block} streaming={streaming} />;
    case "tool":
      return <ToolBlock block={block} />;
    case "plan":
      return <PlanBlock block={block} />;
    case "skill":
      return <SkillBlock block={block} />;
    case "artifact":
      return <ArtifactBlock block={block} />;
    case "error":
      return <ErrorBlock block={block} />;
  }
}

export const BlockView = memo(BlockViewImpl);

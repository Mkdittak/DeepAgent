import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type { Block } from "../../store/types";
import "./TextBlock.css";

type Props = { block: Extract<Block, { kind: "text" }>; streaming: boolean };

// Assistant text is model-authored: rehype-sanitize is mandatory. react-markdown
// does not render raw HTML unless rehype-raw is added (it is not), and sanitize
// strips anything dangerous that survives.
function TextBlockImpl({ block, streaming }: Props) {
  return (
    <div className="da-text">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{block.text}</ReactMarkdown>
      {streaming && <span className="da-cursor" aria-hidden />}
    </div>
  );
}

export const TextBlock = memo(TextBlockImpl);

import "./JumpPill.css";

type Props = { visible: boolean; onClick: () => void };

export function JumpPill({ visible, onClick }: Props) {
  if (!visible) return null;
  return (
    <button className="da-jump" onClick={onClick}>
      ↓ Jump to latest
    </button>
  );
}

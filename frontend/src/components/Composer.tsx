import { useRef, type KeyboardEvent } from "react";
import "./Composer.css";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  running: boolean;
};

// Typing is allowed during a run (intentional change vs legacy): submitting mid
// run appends a new turn to the scrollback rather than being blocked.
export function Composer({ value, onChange, onSubmit, onStop, running }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim()) onSubmit();
    }
  };

  const autosize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  return (
    <div className="da-composer">
      <textarea
        ref={ref}
        className="da-input"
        value={value}
        rows={1}
        placeholder="Ask DeepAgent anything…"
        onChange={(e) => {
          onChange(e.target.value);
          autosize(e.target);
        }}
        onKeyDown={onKeyDown}
      />
      {running ? (
        <button className="da-btn da-stop" onClick={onStop}>Stop</button>
      ) : (
        <button className="da-btn da-send" onClick={onSubmit} disabled={!value.trim()}>Send</button>
      )}
    </div>
  );
}

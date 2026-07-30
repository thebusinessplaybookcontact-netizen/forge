import { useState } from "react";

import { dictationSupported, useDictation } from "../voice";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}

// Inline SVG rather than an emoji: an emoji mic renders at a different size and weight
// on every platform, and can't take the button's colour when the button goes live.
function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="10.5" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" />
      <path d="M12 18v3" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2.5" />
    </svg>
  );
}

export default function Composer({ onSend, disabled, placeholder, autoFocus }: Props) {
  const [value, setValue] = useState("");

  // Dictation sends as soon as you stop talking — the whole point is not having to
  // reach for the keyboard.
  const { listening, transcript, error, toggle } = useDictation((said) => {
    if (!disabled) onSend(said);
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue("");
  }

  return (
    <>
      {error && <p className="chat__error">{error}</p>}
      <form className="composer" onSubmit={submit}>
        {dictationSupported() && (
          <button
            type="button"
            className={`composer__mic${listening ? " composer__mic--live" : ""}`}
            onClick={toggle}
            aria-label={listening ? "Stop talking" : "Talk"}
            aria-pressed={listening}
          >
            {listening ? <StopIcon /> : <MicIcon />}
          </button>
        )}
        <textarea
          className="composer__input"
          value={listening ? transcript : value}
          autoFocus={autoFocus}
          rows={1}
          readOnly={listening}
          placeholder={listening ? "Listening…" : (placeholder ?? "What's going on?")}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter breaks the line.
            if (e.key === "Enter" && !e.shiftKey) submit(e);
          }}
        />
        <button
          className="composer__send"
          type="submit"
          disabled={disabled || listening || !value.trim()}
        >
          Send
        </button>
      </form>
    </>
  );
}

import { useState } from "react";

import { dictationSupported, useDictation } from "../voice";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
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
            {listening ? "■" : "🎙"}
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

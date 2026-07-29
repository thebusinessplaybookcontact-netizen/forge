import { useState } from "react";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}

export default function Composer({ onSend, disabled, placeholder, autoFocus }: Props) {
  const [value, setValue] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue("");
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        className="composer__input"
        value={value}
        autoFocus={autoFocus}
        rows={1}
        placeholder={placeholder ?? "What's going on?"}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends, Shift+Enter breaks the line.
          if (e.key === "Enter" && !e.shiftKey) submit(e);
        }}
      />
      <button className="composer__send" type="submit" disabled={disabled || !value.trim()}>
        Send
      </button>
    </form>
  );
}

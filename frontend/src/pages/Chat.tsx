import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useChatContext } from "../ChatContext";
import ActionNote from "../components/ActionNote";
import Composer from "../components/Composer";

export default function Chat() {
  const { entries, streaming, busy, error, send, undo } = useChatContext();
  const bottom = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const seeded = useRef(false);

  // Home's composer can hand a first message over via router state.
  useEffect(() => {
    const initial = (location.state as { message?: string } | null)?.message;
    if (initial && !seeded.current) {
      seeded.current = true;
      navigate(location.pathname, { replace: true, state: null });
      void send(initial);
    }
  }, [location, navigate, send]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries, streaming]);

  const empty = entries.length === 0 && !streaming;

  return (
    <div className="chat">
      <div className="chat__scroll">
        {empty && (
          <p className="chat__empty">
            Talk to me. Ramble if you want — I'll keep track of what matters.
          </p>
        )}

        {entries.map((entry, i) =>
          entry.kind === "turn" ? (
            <div key={i} className={`bubble bubble--${entry.role}`}>
              {entry.content}
            </div>
          ) : (
            <ActionNote key={i} entry={entry} onUndo={undo} />
          ),
        )}

        {streaming && <div className="bubble bubble--assistant">{streaming}</div>}
        {busy && !streaming && <div className="bubble bubble--assistant bubble--thinking">…</div>}
        {error && <p className="chat__error">{error}</p>}

        <div ref={bottom} />
      </div>

      <Composer onSend={send} disabled={busy} autoFocus />
      {/* Voice input/output lands here in build step 5 (STT in, human TTS out). */}
    </div>
  );
}

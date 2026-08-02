import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useChatContext } from "../ChatContext";
import ActionNote from "../components/ActionNote";
import Composer from "../components/Composer";

export default function Chat() {
  const { entries, streaming, busy, error, send, undo, reset } = useChatContext();
  const bottom = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
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

  /**
   * Follow the reply as it streams — but only if you're already at the bottom.
   *
   * Anchoring unconditionally means you cannot scroll up to re-read anything while the
   * coach is talking: every token yanks you back down. Once you've scrolled away, the
   * screen holds still until you return to the bottom yourself.
   */
  useEffect(() => {
    const view = scroller.current;
    if (!view) return;
    const distance = view.scrollHeight - view.scrollTop - view.clientHeight;
    if (distance < 120) {
      bottom.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [entries, streaming]);

  const empty = entries.length === 0 && !streaming;

  return (
    <div className="chat">
      {!empty && (
        <div className="chat__bar">
          <button className="row__edit" type="button" onClick={reset} disabled={busy}>
            Start fresh
          </button>
        </div>
      )}

      <div className="chat__scroll" ref={scroller}>
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

        {/* Announced politely so the reply reaches a screen reader as it arrives. */}
        <div aria-live="polite" aria-atomic="false">
          {streaming && <div className="bubble bubble--assistant">{streaming}</div>}
          {busy && !streaming && (
            <div className="bubble bubble--assistant bubble--thinking">Thinking…</div>
          )}
        </div>
        {error && <p className="chat__error">{error}</p>}

        <div ref={bottom} />
      </div>

      <Composer onSend={send} disabled={busy} autoFocus />
      {/* Voice input/output lands here in build step 5 (STT in, human TTS out). */}
    </div>
  );
}

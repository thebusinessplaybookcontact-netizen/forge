import { useCallback, useRef, useState } from "react";

import { streamChat } from "./api";
import type { ChatTurn } from "./types";

/**
 * The chat loop. Owns the turn list, the streaming assistant reply, and the
 * session id the backend assigns on the first message.
 *
 * Only the current session's turns are sent back up. Everything older reaches the
 * model as a summary, assembled server-side — see backend/app/memory.py.
 */
export function useChat() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [streaming, setStreaming] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<number | null>(null);

  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || busy) return;

      setError(null);
      setBusy(true);
      // Snapshot history *before* adding this turn — the backend appends it itself.
      const history = turns;
      setTurns((prev) => [...prev, { role: "user", content: text }]);
      setStreaming("");

      let reply = "";
      try {
        await streamChat(
          { message: text, session_id: sessionId.current, history },
          {
            onSession: (id) => {
              sessionId.current = id;
            },
            onDelta: (delta) => {
              reply += delta;
              setStreaming(reply);
            },
            onError: (msg) => setError(msg),
          },
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }

      if (reply.trim()) {
        setTurns((prev) => [...prev, { role: "assistant", content: reply.trim() }]);
      }
      setStreaming("");
      setBusy(false);
    },
    [busy, turns],
  );

  return { turns, streaming, busy, error, send, sessionId };
}

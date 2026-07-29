import { useCallback, useRef, useState } from "react";

import { streamChat, undoChange, type ToolActionEvent } from "./api";
import type { ChatTurn } from "./types";

/** A turn, or a note about something the coach changed while replying. */
export type Entry =
  | { kind: "turn"; role: "user" | "assistant"; content: string }
  | { kind: "action"; action: ToolActionEvent; undone?: boolean };

/**
 * The chat loop. Owns the entry list, the streaming assistant reply, and the
 * session id the backend assigns on the first message.
 *
 * Only the current session's *turns* are sent back up — action notes are display-only,
 * and everything older than this session reaches the model as a summary. See
 * backend/app/memory.py.
 */
export function useChat() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [streaming, setStreaming] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const sessionId = useRef<number | null>(null);

  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || busy) return;

      setError(null);
      setBusy(true);
      // Snapshot history *before* adding this turn — the backend appends it itself.
      const history: ChatTurn[] = entries
        .filter((e): e is Extract<Entry, { kind: "turn" }> => e.kind === "turn")
        .map((e) => ({ role: e.role, content: e.content }));

      setEntries((prev) => [...prev, { kind: "turn", role: "user", content: text }]);
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
            onAction: (action) => {
              // Flush any text streamed before the tool call so ordering survives.
              setEntries((prev) => {
                const next = [...prev];
                if (reply.trim()) {
                  next.push({ kind: "turn", role: "assistant", content: reply.trim() });
                  reply = "";
                }
                next.push({ kind: "action", action });
                return next;
              });
              setStreaming("");
              // Signals screens showing goals/tasks that their data is now stale.
              setChanged((n) => n + 1);
            },
            onError: (msg) => setError(msg),
          },
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }

      if (reply.trim()) {
        setEntries((prev) => [...prev, { kind: "turn", role: "assistant", content: reply.trim() }]);
      }
      setStreaming("");
      setBusy(false);
    },
    [busy, entries],
  );

  /** Take back a change, then let the dashboard know its data moved again. */
  const undo = useCallback(async (undoId: number) => {
    try {
      await undoChange(undoId);
      setEntries((prev) =>
        prev.map((e) =>
          e.kind === "action" && e.action.undo_id === undoId ? { ...e, undone: true } : e,
        ),
      );
      setChanged((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  return { entries, streaming, busy, error, send, undo, sessionId, changed };
}

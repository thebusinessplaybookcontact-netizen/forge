import { useCallback, useEffect, useRef, useState } from "react";

import { streamChat, undoChange, type ToolActionEvent } from "./api";
import type { ChatTurn } from "./types";

/** A turn, or a note about something the coach changed while replying. */
export type Entry =
  | { kind: "turn"; role: "user" | "assistant"; content: string }
  | { kind: "action"; action: ToolActionEvent; undone?: boolean };

const STORE_KEY = "coach.conversation";

/**
 * How long a restored conversation is still the *same* conversation.
 *
 * Deliberately shorter than the server's COACH_SESSION_IDLE_MINUTES (45): past that
 * the backend has written the conversation's recap and closed it, and picking it up
 * again would mean turns landing after the summary that no summary will ever cover.
 * Being the more cautious of the two means we start a new session slightly early
 * rather than resuming a dead one — and the coach still remembers, because that's
 * exactly what the recap is for.
 */
const RESUME_WINDOW_MS = 30 * 60 * 1000;

/** Enough to scroll back through, bounded so storage can't grow forever. */
const MAX_STORED = 60;

interface Stored {
  entries: Entry[];
  sessionId: number | null;
  at: number;
}

function load(): Stored | null {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as Stored;
    if (!Array.isArray(saved.entries) || Date.now() - saved.at > RESUME_WINDOW_MS) {
      localStorage.removeItem(STORE_KEY);
      return null;
    }
    return saved;
  } catch {
    // Corrupt or unavailable storage must never stop the app opening.
    return null;
  }
}

/**
 * The chat loop. Owns the entry list, the streaming assistant reply, and the
 * session id the backend assigns on the first message.
 *
 * Only the current session's *turns* are sent back up — action notes are display-only,
 * and everything older than this session reaches the model as a summary. See
 * backend/app/memory.py.
 *
 * The conversation is mirrored into localStorage because on a phone this app does not
 * stay running: lock the screen, take a call, switch apps for thirty seconds, and the
 * webview is killed. Without this you come back mid-conversation to a blank screen.
 */
export function useChat() {
  const restored = useRef(load());
  const [entries, setEntries] = useState<Entry[]>(restored.current?.entries ?? []);
  const [streaming, setStreaming] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  // The most recently finished reply. Carries a sequence number so a repeated identical
  // reply still counts as new — otherwise it would silently not be spoken.
  const [lastReply, setLastReply] = useState<{ seq: number; text: string } | null>(null);
  const sessionId = useRef<number | null>(restored.current?.sessionId ?? null);
  const replySeq = useRef(0);

  // Mirror after every settled change. Not during streaming — a write per token would
  // be pointless churn, and a half-arrived reply isn't worth restoring.
  useEffect(() => {
    if (entries.length === 0) {
      localStorage.removeItem(STORE_KEY);
      return;
    }
    try {
      const payload: Stored = {
        entries: entries.slice(-MAX_STORED),
        sessionId: sessionId.current,
        at: Date.now(),
      };
      localStorage.setItem(STORE_KEY, JSON.stringify(payload));
    } catch {
      // Private mode, quota, whatever. Losing the mirror is not losing the app.
    }
  }, [entries]);

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
        replySeq.current += 1;
        setLastReply({ seq: replySeq.current, text: reply.trim() });
      }
      setStreaming("");
      setBusy(false);
    },
    [busy, entries],
  );

  /**
   * Put the screen back to empty and start a new conversation.
   *
   * Deliberately doesn't tell the server to close anything: the conversation really
   * happened, and the idle sweep will summarise it in its own time. Clearing the view
   * shouldn't erase the coach's memory of it.
   */
  const reset = useCallback(() => {
    setEntries([]);
    setStreaming("");
    setError(null);
    sessionId.current = null;
    try {
      localStorage.removeItem(STORE_KEY);
    } catch {
      /* nothing to do if storage is unavailable */
    }
  }, []);

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

  return { entries, streaming, busy, error, send, undo, reset, sessionId, changed, lastReply };
}

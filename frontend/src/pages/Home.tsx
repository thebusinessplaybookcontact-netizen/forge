import { useCallback, useEffect, useState } from "react";

import { getDashboard, updateTask } from "../api";
import { useChatContext } from "../ChatContext";
import { todayISO } from "../dates";
import ActionNote from "../components/ActionNote";
import Composer from "../components/Composer";
import type { Dashboard } from "../types";

/**
 * Due dates carry state, not just a value — something overdue should be visible without
 * reading and comparing dates. Both ISO strings, so lexicographic comparison is correct.
 */
function DueChip({ due, today }: { due: string; today: string }) {
  const tone = due < today ? "overdue" : due === today ? "today" : "later";
  const label = tone === "overdue" ? "overdue" : tone === "today" ? "today" : due.slice(5);
  return <span className={`chip chip--${tone}`}>{label}</span>;
}

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { entries, streaming, busy, send, undo, changed } = useChatContext();

  const load = useCallback(() => {
    getDashboard()
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  // Refetch on mount, then every time the coach changes something. `changed` only
  // increments on an actual tool action or undo, so this is event-driven — no polling.
  useEffect(load, [load, changed]);

  async function complete(id: number) {
    await updateTask(id, { status: "done" });
    load();
  }

  // The tail of the conversation, so talking from this screen is useful without
  // leaving it. The full transcript lives on /chat.
  const recent = entries.slice(-4);
  const today = todayISO();

  return (
    <div className="home">
      <header className="home__header">
        <h1 className="home__title">Today</h1>
      </header>

      {error && <p className="chat__error">{error}</p>}

      <section className="panel">
        <h2 className="panel__title">Quests</h2>
        {!data && <p className="muted">Loading…</p>}
        {data && data.open_tasks.length === 0 && (
          <p className="muted">Nothing open. Either you're ahead, or you're avoiding something.</p>
        )}
        <ul className="tasks">
          {data?.open_tasks.map((task) => (
            <li key={task.id} className="tasks__item">
              <button
                className="tasks__check"
                onClick={() => complete(task.id)}
                aria-label={`Mark "${task.text}" done`}
              />
              <span className="tasks__text">{task.text}</span>
              {task.due && <DueChip due={task.due} today={today} />}
            </li>
          ))}
        </ul>
      </section>

      {data && data.recent_summaries.length > 0 && (
        <section className="panel">
          <h2 className="panel__title">Last time</h2>
          <p className="recap">{data.recent_summaries[0].recap}</p>
        </section>
      )}

      <section className="home__composer">
        {recent.length > 0 && (
          <div className="home__tail">
            {recent.map((entry, i) =>
              entry.kind === "turn" ? (
                <p key={i} className={`tail tail--${entry.role}`}>
                  {entry.content}
                </p>
              ) : (
                <ActionNote key={i} entry={entry} onUndo={undo} />
              ),
            )}
            {streaming && <p className="tail tail--assistant">{streaming}</p>}
          </div>
        )}
        <Composer onSend={send} disabled={busy} placeholder="Talk to your coach…" />
      </section>
    </div>
  );
}

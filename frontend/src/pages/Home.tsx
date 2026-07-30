import { useCallback, useEffect, useState } from "react";

import { getDashboard, logHabit, unlogHabit, updateTask } from "../api";
import { useChatContext } from "../ChatContext";
import { todayISO } from "../dates";
import ActionNote from "../components/ActionNote";
import Composer from "../components/Composer";
import DueChip from "../components/DueChip";
import HabitRow, { weekMet } from "../components/HabitRow";
import type { Dashboard, Habit } from "../types";

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

  /** Tick today's habit. The response carries the recomputed streak, so patch in place
      rather than refetching the whole dashboard for one boolean. */
  async function toggleHabit(habit: Habit) {
    try {
      const updated = habit.done_today ? await unlogHabit(habit.id) : await logHabit(habit.id);
      setData((current) =>
        current
          ? { ...current, habits: current.habits.map((h) => (h.id === updated.id ? updated : h)) }
          : current,
      );
    } catch (e) {
      setError(String(e));
    }
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

      {data && data.habits.length > 0 && (
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Habits</h2>
            {/* Weekly habits that already hit their target count as done — a 3×/week
                habit finished on Thursday shouldn't drag the day's count down. */}
            <span className="panel__count">
              {data.habits.filter((h) => h.done_today || weekMet(h)).length}/{data.habits.length}
            </span>
          </div>
          <ul className="habits">
            {data.habits.map((habit) => (
              <HabitRow key={habit.id} habit={habit} onToggle={() => toggleHabit(habit)} />
            ))}
          </ul>
        </section>
      )}

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

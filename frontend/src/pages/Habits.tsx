import { useCallback, useEffect, useState } from "react";

import {
  createHabit,
  deleteHabit,
  getGoals,
  getHabits,
  logHabit,
  undoChange,
  unlogHabit,
  updateHabit,
} from "../api";
import { useChatContext } from "../ChatContext";
import HabitCard from "../components/HabitCard";
import type { Cadence, Goal, Habit } from "../types";

interface Undoable {
  undoId: number;
  label: string;
}

export default function Habits() {
  const [habits, setHabits] = useState<Habit[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [undoable, setUndoable] = useState<Undoable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { changed } = useChatContext();

  const [text, setText] = useState("");
  const [cadence, setCadence] = useState<Cadence>("daily");
  const [target, setTarget] = useState(3);

  const refresh = useCallback(async () => {
    const [h, g] = await Promise.all([getHabits(), getGoals()]);
    setHabits(h);
    setGoals(g);
  }, []);

  // Also refetches when the coach adds or logs a habit mid-conversation.
  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh, changed]);

  const run = useCallback(
    async (work: () => Promise<unknown>) => {
      setError(null);
      try {
        await work();
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh],
  );

  /**
   * Ticking writes through and swaps in the stats the server just recomputed, so the
   * streak updates on the same frame as the checkbox — no refetch, no flicker.
   */
  async function toggleDay(habit: Habit, iso: string, done: boolean) {
    setError(null);
    try {
      const updated = done ? await unlogHabit(habit.id, iso) : await logHabit(habit.id, iso);
      setHabits((current) => current.map((h) => (h.id === updated.id ? updated : h)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await run(() =>
      createHabit({
        text: text.trim(),
        cadence,
        target_per_week: cadence === "weekly" ? target : 7,
      }),
    );
    setText("");
  }

  return (
    <div className="habits-page">
      <header className="home__header">
        <h1 className="home__title">Habits</h1>
      </header>

      {error && <p className="chat__error">{error}</p>}

      {undoable && (
        <div className="undo-bar" role="status">
          <span>Deleted “{undoable.label}”</span>
          <button
            className="action__undo"
            type="button"
            onClick={() =>
              run(async () => {
                await undoChange(undoable.undoId);
                setUndoable(null);
              })
            }
          >
            Undo
          </button>
          <button className="undo-bar__dismiss" type="button" onClick={() => setUndoable(null)}>
            Dismiss
          </button>
        </div>
      )}

      {habits.length === 0 && (
        <p className="muted">
          Nothing repeating yet. Habits are the ones you do again and again — the goals
          take care of themselves after that.
        </p>
      )}

      {habits.map((habit) => (
        <HabitCard
          key={habit.id}
          habit={habit}
          goals={goals}
          onToggleDay={(iso, done) => toggleDay(habit, iso, done)}
          onSave={(patch) => run(() => updateHabit(habit.id, patch))}
          onDelete={() =>
            run(async () => {
              const { undo_id } = await deleteHabit(habit.id);
              setUndoable({ undoId: undo_id, label: habit.text });
            })
          }
        />
      ))}

      <section className="panel">
        <h2 className="panel__title">Add a habit</h2>
        <form className="form" onSubmit={add}>
          <input
            className="input"
            value={text}
            placeholder="What do you want to do repeatedly?"
            aria-label="Habit"
            onChange={(e) => setText(e.target.value)}
          />
          <div className="form__pair">
            <label className="field">
              <span className="field__label">Cadence</span>
              <select
                className="input"
                value={cadence}
                onChange={(e) => setCadence(e.target.value as Cadence)}
              >
                <option value="daily">Every day</option>
                <option value="weekly">Some days</option>
              </select>
            </label>
            {cadence === "weekly" && (
              <label className="field">
                <span className="field__label">Times a week</span>
                <select
                  className="input"
                  value={target}
                  onChange={(e) => setTarget(Number(e.target.value))}
                >
                  {[1, 2, 3, 4, 5, 6].map((n) => (
                    <option key={n} value={n}>
                      {n}×
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <button className="button" type="submit">
            Add habit
          </button>
        </form>
        {/* Said once, here, where the choice is made — a schedule you can actually keep
            beats a daily one you break on Wednesday. */}
        <p className="muted habits-page__hint">
          Three times a week that holds is worth more than every day that doesn't.
        </p>
      </section>
    </div>
  );
}

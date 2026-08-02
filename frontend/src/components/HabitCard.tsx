import { useState } from "react";

import { todayISO } from "../dates";
import type { Cadence, Goal, Habit } from "../types";
import HabitGrid from "./HabitGrid";
import HabitRow from "./HabitRow";

interface Props {
  habit: Habit;
  goals: Goal[];
  onToggleDay: (iso: string, done: boolean) => void;
  onSave: (patch: Partial<Habit>) => Promise<void>;
  onDelete: () => Promise<void>;
}

const TARGETS = [1, 2, 3, 4, 5, 6];

/**
 * The line under the chain. Carries the week-streak that the row's status line drops,
 * and when there's no history yet it explains what the squares are for instead.
 */
function foot(habit: Habit): string {
  const unit = habit.cadence === "weekly" ? "week" : "day";
  // "best 1 days" is the kind of thing that makes an app feel unfinished.
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

  if (habit.cadence === "weekly" && habit.current_streak > 0) {
    return `${habit.current_streak}-week streak · best ${plural(habit.longest_streak, "week")}`;
  }
  if (habit.longest_streak > 0) return `Best run: ${plural(habit.longest_streak, unit)}`;
  return "Tap a square to fill in a day you missed.";
}

/** One habit, with its chain. The grid stays open — seeing it is the whole point. */
export default function HabitCard({ habit, goals, onToggleDay, onSave, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(habit.text);
  const [why, setWhy] = useState(habit.why ?? "");
  const [cadence, setCadence] = useState<Cadence>(habit.cadence);
  const [target, setTarget] = useState(habit.target_per_week);
  const [goalId, setGoalId] = useState<number | "">(habit.linked_goal_id ?? "");
  const [busy, setBusy] = useState(false);

  function open() {
    setText(habit.text);
    setWhy(habit.why ?? "");
    setCadence(habit.cadence);
    setTarget(habit.target_per_week);
    setGoalId(habit.linked_goal_id ?? "");
    setEditing(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    await onSave({
      text: text.trim(),
      why: why.trim() || null,
      cadence,
      target_per_week: cadence === "weekly" ? target : 7,
      linked_goal_id: goalId === "" ? null : goalId,
    });
    setBusy(false);
    setEditing(false);
  }

  if (editing) {
    return (
      <form className="habit-card form" onSubmit={save}>
        <input
          className="input"
          value={text}
          aria-label="Habit"
          onChange={(e) => setText(e.target.value)}
        />
        <input
          className="input"
          value={why}
          placeholder="Why does it matter?"
          aria-label="Why it matters"
          onChange={(e) => setWhy(e.target.value)}
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
                {TARGETS.map((n) => (
                  <option key={n} value={n}>
                    {n}×
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <label className="field">
          <span className="field__label">Goal</span>
          <select
            className="input"
            value={goalId}
            onChange={(e) => setGoalId(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">None</option>
            {goals.map((g) => (
              <option key={g.id} value={g.id}>
                {g.text}
              </option>
            ))}
          </select>
        </label>
        <div className="form__actions">
          <button className="button" type="submit" disabled={busy || !text.trim()}>
            Save
          </button>
          <button className="button button--quiet" type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            className="button button--danger"
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await onDelete();
              setBusy(false);
            }}
          >
            Delete
          </button>
        </div>
      </form>
    );
  }

  return (
    <article className="habit-card">
      <ul className="habits">
        <HabitRow
          habit={habit}
          onToggle={() => onToggleDay(todayISO(), habit.done_today)}
          trailing={
            <button className="row__edit" type="button" onClick={open}>
              Edit
            </button>
          }
        />
      </ul>

      <HabitGrid habit={habit} onToggle={onToggleDay} />

      <p className="habit-card__foot">
        {foot(habit)}
        {habit.why && <span className="habit-card__why"> — {habit.why}</span>}
      </p>
    </article>
  );
}

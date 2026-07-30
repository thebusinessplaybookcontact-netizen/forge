import type { Habit } from "../types";

interface Props {
  habit: Habit;
  onToggle: () => void;
  /** Rendered at the end of the row — the Habits screen puts an Edit button here. */
  trailing?: React.ReactNode;
}

/**
 * How a habit describes itself in one line.
 *
 * Deliberately never says "0 day streak". A reset chain is the moment people quit, and
 * a counter reading zero is the thing that tells them to. It says what to do instead,
 * and the consistency figure alongside keeps a truer number on screen — one missed day
 * doesn't undo six weeks, so the UI shouldn't imply it did.
 */
export function statusLine(habit: Habit): string {
  const parts: string[] = [];
  const pct = Math.round(habit.completion_rate_30d * 100);

  // Two facts, one line. A third makes the row wrap on a phone, and the week-streak —
  // the one that gets cut — is on the habit's own card a scroll away.
  if (habit.cadence === "weekly") {
    parts.push(
      weekMet(habit)
        ? "Done for the week"
        : `${habit.this_week} of ${habit.target_per_week} this week`,
    );
  } else if (habit.current_streak > 0) {
    parts.push(`${habit.current_streak}-day streak`);
  } else if (habit.longest_streak > 0) {
    parts.push("Pick it back up today");
  } else {
    parts.push("Not started yet");
  }

  if (habit.longest_streak > 0) parts.push(`${pct}% consistent`);
  return parts.join(" · ");
}

/** True once a weekly habit has met its target — it's finished, not behind. */
export function weekMet(habit: Habit): boolean {
  return habit.cadence === "weekly" && habit.this_week >= habit.target_per_week;
}

/** The last seven days, oldest first, ending today. */
export function lastWeek(habit: Habit): boolean[] {
  return habit.grid.slice(-7);
}

export default function HabitRow({ habit, onToggle, trailing }: Props) {
  const done = habit.done_today;
  const met = weekMet(habit);

  return (
    <li className={`habit${done ? " habit--done" : ""}`}>
      <button
        type="button"
        className={`habit__tick${done ? " habit__tick--done" : ""}`}
        onClick={onToggle}
        aria-pressed={done}
        aria-label={`Mark "${habit.text}" ${done ? "not done today" : "done today"}`}
      >
        {done ? "✓" : ""}
      </button>

      <div className="habit__body">
        <p className="habit__text">{habit.text}</p>
        <p className={`habit__meta${met ? " habit__meta--met" : ""}`}>{statusLine(habit)}</p>
      </div>

      {/* The week at a glance, today on the right. Small enough to be texture rather
          than a second thing to read. */}
      <span className="habit__week" aria-hidden="true">
        {lastWeek(habit).map((on, i) => (
          <span key={i} className={`habit__dot${on ? " habit__dot--on" : ""}`} />
        ))}
      </span>

      {trailing}
    </li>
  );
}

import { addDays, mondayIndex, niceDate, parseISO, todayISO } from "../dates";
import type { Habit } from "../types";

interface Props {
  habit: Habit;
  /** Tap a square to fix a day you forgot to tick. Omit for a read-only grid. */
  onToggle?: (iso: string, done: boolean) => void;
}

interface Cell {
  iso: string;
  done: boolean;
}

/**
 * The chain. Nine weeks as columns, weekdays as rows — the same shape as a GitHub
 * contribution graph, because it's the one grid people already know how to read: you
 * see the pattern (weekends always blank, a bad fortnight in March) rather than a
 * number that claims to summarise it.
 *
 * The backend's window ends today and is 63 days long, which is nine weeks but not
 * week-aligned, so the first column gets padded to put every square under the right
 * weekday.
 */
export default function HabitGrid({ habit, onToggle }: Props) {
  const start = parseISO(habit.grid_start);
  const pad = mondayIndex(start);

  // Column-major: one array per week, Monday first. Padding cells are null, and stay
  // inert — they're layout, not days.
  const columns: (Cell | null)[][] = [];
  let column: (Cell | null)[] = Array(pad).fill(null);

  habit.grid.forEach((done, i) => {
    column.push({ iso: todayISO(addDays(start, i)), done });
    if (column.length === 7) {
      columns.push(column);
      column = [];
    }
  });
  if (column.length) {
    columns.push([...column, ...Array(7 - column.length).fill(null)]);
  }

  const today = todayISO();

  return (
    <div className="chain">
      {/* Mon/Wed/Fri only, the same shorthand a contribution graph uses — enough to
          orient the rows without labelling all seven. */}
      <div className="chain__days" aria-hidden="true">
        {["M", "", "W", "", "F", "", ""].map((day, i) => (
          <span key={i}>{day}</span>
        ))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr)` }}>
        {columns.map((week, w) =>
        week.map((cell, d) => {
          if (!cell) return <span key={`${w}-${d}`} className="grid__pad" aria-hidden="true" />;

          const label = `${niceDate(cell.iso)}: ${cell.done ? "done" : "not done"}`;
          const className = [
            "grid__cell",
            cell.done && "grid__cell--done",
            cell.iso === today && "grid__cell--today",
          ]
            .filter(Boolean)
            .join(" ");

          if (!onToggle) return <span key={cell.iso} className={className} title={label} />;

          return (
            <button
              key={cell.iso}
              type="button"
              className={className}
              title={label}
              aria-label={label}
              aria-pressed={cell.done}
              onClick={() => onToggle(cell.iso, cell.done)}
            />
          );
        }),
        )}
      </div>
    </div>
  );
}

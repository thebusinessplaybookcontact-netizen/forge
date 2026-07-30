import { addDays, parseISO, todayISO } from "../dates";

const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: "short" });
const MONTH_DAY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/**
 * Due dates carry state, not just a value — something overdue should be visible without
 * reading and comparing dates. Both sides are ISO, so string comparison is correct.
 *
 * The label is the shortest thing that still means something: tomorrow and the days
 * after it are named ("Fri"), because "Fri" is read at a glance and "07-31" has to be
 * decoded — and inside a goal's nested step list, the width saved is the difference
 * between a task fitting on one line and wrapping.
 */
export default function DueChip({ due, today = todayISO() }: { due: string; today?: string }) {
  const tone = due < today ? "overdue" : due === today ? "today" : "later";

  let label: string;
  if (tone === "overdue") label = "overdue";
  else if (tone === "today") label = "today";
  else if (due === todayISO(addDays(parseISO(today), 1))) label = "tomorrow";
  else if (due < todayISO(addDays(parseISO(today), 7))) label = WEEKDAY.format(parseISO(due));
  else label = MONTH_DAY.format(parseISO(due));

  return <span className={`chip chip--${tone}`}>{label}</span>;
}

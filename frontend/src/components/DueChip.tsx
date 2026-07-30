import { todayISO } from "../dates";

/**
 * Due dates carry state, not just a value — something overdue should be visible without
 * reading and comparing dates. Both sides are ISO, so string comparison is correct.
 */
export default function DueChip({ due, today = todayISO() }: { due: string; today?: string }) {
  const tone = due < today ? "overdue" : due === today ? "today" : "later";
  const label = tone === "overdue" ? "overdue" : tone === "today" ? "today" : due.slice(5);
  return <span className={`chip chip--${tone}`}>{label}</span>;
}

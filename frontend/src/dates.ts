/**
 * Today, as the phone's clock sees it.
 *
 * `toISOString().slice(0, 10)` looks like the obvious way to get YYYY-MM-DD and is
 * wrong: it converts to UTC first, so anywhere west of Greenwich it flips to tomorrow
 * during the evening and every task due today starts rendering as overdue.
 */
export function todayISO(date = new Date()): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * Parse YYYY-MM-DD as a *local* date.
 *
 * `new Date("2026-07-30")` is parsed as UTC midnight by spec, which lands on the 29th
 * for anyone behind Greenwich — the same off-by-one-day bug as above, in reverse.
 */
export function parseISO(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** Monday = 0 … Sunday = 6, matching the backend's week_start(). */
export function mondayIndex(date: Date): number {
  return (date.getDay() + 6) % 7;
}

const NICE = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" });

export function niceDate(iso: string): string {
  return NICE.format(parseISO(iso));
}

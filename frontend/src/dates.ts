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

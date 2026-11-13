// Journal days are plain "YYYY-MM-DD" strings decided by the server. These helpers do
// calendar arithmetic on them in UTC so the browser's own timezone never shifts a day.

export function parseDay(day: string): Date {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function formatDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1 + by, 1)).toISOString().slice(0, 7);
}

export function monthLabel(month: string): string {
  return parseDay(`${month}-01`).toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
}

export function dayLabel(day: string): string {
  return parseDay(day).toLocaleDateString(undefined, {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  });
}

/** The weeks of a month as rows of seven days (Sunday first); days outside the month are null. */
export function monthGrid(month: string): (string | null)[][] {
  const first = parseDay(`${month}-01`);
  const cells: (string | null)[] = Array(first.getUTCDay()).fill(null);
  for (const d = new Date(first); d.toISOString().slice(0, 7) === month; d.setUTCDate(d.getUTCDate() + 1)) {
    cells.push(formatDay(d));
  }
  while (cells.length % 7) cells.push(null);
  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** A stored UTC timestamp as a clock time in the user's configured timezone. */
export function clockTime(iso: string, timezone: string): string {
  const date = new Date(iso);
  try {
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZone: timezone });
  } catch {
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }
}

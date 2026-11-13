import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useJournalStore } from '../../stores/journalStore';
import { monthGrid, monthLabel, shiftMonth } from './dates';

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

interface JournalCalendarProps {
  onSelect?: () => void;
}

/** Month grid for the sidebar: days with entries are marked, future days cannot be opened. */
export function JournalCalendar({ onSelect }: JournalCalendarProps) {
  const today = useJournalStore((s) => s.today);
  const month = useJournalStore((s) => s.month);
  const days = useJournalStore((s) => s.days);
  const selectedDay = useJournalStore((s) => s.selectedDay);
  const showMonth = useJournalStore((s) => s.showMonth);
  const selectDay = useJournalStore((s) => s.selectDay);

  if (!month || !today) {
    return <div className="p-4 text-sm text-slate-500 dark:text-slate-400">Loading…</div>;
  }

  const currentMonth = today.slice(0, 7);
  const written = Object.keys(days).length;
  const open = (day: string) => {
    selectDay(day);
    onSelect?.();
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
        <h2 className="font-semibold text-sm">Journal</h2>
        <button
          onClick={() => {
            if (month !== currentMonth) showMonth(currentMonth);
            open(today);
          }}
          className="text-xs px-2 py-1 rounded border border-slate-300 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
        >
          Today
        </button>
      </div>

      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <button
            onClick={() => showMonth(shiftMonth(month, -1))}
            className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            aria-label="Previous month"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium">{monthLabel(month)}</span>
          <button
            onClick={() => showMonth(shiftMonth(month, 1))}
            disabled={month >= currentMonth}
            className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
            aria-label="Next month"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        <div className="grid grid-cols-7 gap-1 text-center">
          {WEEKDAYS.map((label, i) => (
            <div key={i} className="text-[11px] font-medium text-slate-400 dark:text-slate-500 py-1">{label}</div>
          ))}
          {monthGrid(month).flat().map((day, i) => {
            if (!day) return <div key={i} />;
            const count = days[day] ?? 0;
            const future = day > today;
            const selected = day === selectedDay;
            return (
              <button
                key={day}
                onClick={() => open(day)}
                disabled={future}
                aria-label={`${day}${count ? `, ${count} ${count === 1 ? 'entry' : 'entries'}` : ''}`}
                aria-pressed={selected}
                className={cn(
                  'relative aspect-square rounded-lg text-sm tabular-nums transition-colors flex items-center justify-center',
                  future && 'text-slate-300 dark:text-slate-600 cursor-default',
                  !future && !selected && 'hover:bg-slate-200 dark:hover:bg-slate-700',
                  selected && 'bg-blue-600 text-white font-semibold wt-accent-bg',
                  !selected && day === today && 'ring-1 ring-inset ring-blue-500 text-blue-600 dark:text-blue-400 font-semibold',
                )}
              >
                {Number(day.slice(8))}
                {count > 0 && (
                  <span className={cn(
                    'absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full',
                    selected ? 'bg-white' : 'bg-blue-500',
                  )} />
                )}
              </button>
            );
          })}
        </div>

        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          {written === 0 ? 'Nothing written this month.' : `${written} ${written === 1 ? 'day' : 'days'} written this month.`}
        </p>
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { AlertCircle, Loader2, NotebookPen, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useJournalStore } from '../../stores/journalStore';
import { dayLabel } from './dates';
import { EntryCard } from './EntryCard';
import { JournalChat } from './JournalChat';

const DRAFT_KEY = 'journal-draft';

/** The open day: its entries and a box to write another, with the side conversation beside it. */
export function JournalView() {
  const today = useJournalStore((s) => s.today);
  const selectedDay = useJournalStore((s) => s.selectedDay);
  const entries = useJournalStore((s) => s.entries);
  const loadingDay = useJournalStore((s) => s.loadingDay);
  const saving = useJournalStore((s) => s.saving);
  const error = useJournalStore((s) => s.error);
  const init = useJournalStore((s) => s.init);
  const addEntry = useJournalStore((s) => s.addEntry);
  const dismissError = useJournalStore((s) => s.dismissError);
  const [pane, setPane] = useState<'write' | 'talk'>('write');
  // Unsaved writing survives a reload or a tab switch; it is kept only in this browser.
  const [draft, setDraft] = useState(() => {
    try { return localStorage.getItem(DRAFT_KEY) ?? ''; } catch { return ''; }
  });

  useEffect(() => { init(); }, [init]);

  useEffect(() => {
    try {
      if (draft) localStorage.setItem(DRAFT_KEY, draft);
      else localStorage.removeItem(DRAFT_KEY);
    } catch { /* storage unavailable */ }
  }, [draft]);

  const save = async () => {
    if (!draft.trim() || saving) return;
    if (await addEntry(draft)) setDraft('');
  };

  if (!selectedDay || !today) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 dark:text-slate-400">
        {error ? (
          <span className="flex items-center gap-2 text-sm"><AlertCircle className="w-4 h-4" /> {error}</span>
        ) : (
          <Loader2 className="w-6 h-6 animate-spin" />
        )}
      </div>
    );
  }

  const isToday = selectedDay === today;

  return (
    <div className="flex-1 flex min-h-0 overflow-hidden">
      <section className={cn('flex-1 min-w-0 flex-col min-h-0', pane === 'write' ? 'flex' : 'hidden lg:flex')}>
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="max-w-3xl mx-auto flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">
                {isToday ? 'Today' : 'Journal'}
              </p>
              <p className="text-base font-medium truncate">{dayLabel(selectedDay)}</p>
            </div>
            <PaneSwitch pane={pane} onChange={setPane} />
          </div>
        </div>

        {error && (
          <div className="px-4 pt-3 shrink-0">
            <div role="alert" className="max-w-3xl mx-auto flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span className="flex-1">{error}</span>
              <button onClick={dismissError} aria-label="Dismiss" className="p-0.5 rounded hover:bg-amber-100 dark:hover:bg-amber-900/40">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="max-w-3xl mx-auto space-y-3">
            {loadingDay ? (
              <div className="flex justify-center py-10 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /></div>
            ) : entries.length === 0 ? (
              <div className="text-center text-slate-500 dark:text-slate-400 py-10">
                <NotebookPen className="w-9 h-9 mx-auto mb-3 opacity-50" />
                <p className="text-sm">{isToday ? 'Nothing written yet today.' : 'Nothing was written on this day.'}</p>
                <p className="text-xs mt-1">
                  {isToday ? 'Write below, or ask for a prompt in the conversation.' : 'You can still add an entry for it below.'}
                </p>
              </div>
            ) : (
              entries.map((entry) => <EntryCard key={entry.id} entry={entry} />)
            )}
          </div>
        </div>

        <div className="border-t border-slate-200 dark:border-slate-700 px-4 py-3 shrink-0 safe-area-inset-bottom">
          <div className="max-w-3xl mx-auto">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  save();
                }
              }}
              rows={4}
              maxLength={20000}
              placeholder={isToday ? 'What happened today? What is on your mind?' : `Add an entry for ${dayLabel(selectedDay)}…`}
              aria-label="New journal entry"
              className="w-full resize-y rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-[15px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="mt-2 flex items-center gap-3">
              <p className="flex-1 text-xs text-slate-400 dark:text-slate-500">
                Saved entries are added to the assistant&apos;s memory. <span className="hidden sm:inline">⌘/Ctrl + Enter to save.</span>
              </p>
              <button
                onClick={save}
                disabled={!draft.trim() || saving}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors wt-accent-bg"
              >
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                Save entry
              </button>
            </div>
          </div>
        </div>
      </section>

      <aside className={cn(
        'lg:w-[380px] lg:shrink-0 lg:border-l border-slate-200 dark:border-slate-700 flex-col min-h-0',
        pane === 'talk' ? 'flex flex-1 lg:flex-none' : 'hidden lg:flex',
      )}>
        <div className="lg:hidden px-4 py-2 border-b border-slate-200 dark:border-slate-700 flex items-center gap-3 shrink-0">
          <p className="flex-1 text-sm font-medium truncate">{dayLabel(selectedDay)}</p>
          <PaneSwitch pane={pane} onChange={setPane} />
        </div>
        <JournalChat />
      </aside>
    </div>
  );
}

/** On narrow screens the entries and the conversation share the space; this switches between them. */
function PaneSwitch({ pane, onChange }: { pane: 'write' | 'talk'; onChange: (pane: 'write' | 'talk') => void }) {
  return (
    <div className="lg:hidden inline-flex rounded-lg border border-slate-300 dark:border-slate-600 p-0.5 text-xs shrink-0">
      {(['write', 'talk'] as const).map((value) => (
        <button
          key={value}
          onClick={() => onChange(value)}
          aria-pressed={pane === value}
          className={cn(
            'px-3 py-1 rounded-md transition-colors',
            pane === value ? 'bg-blue-600 text-white wt-accent-bg' : 'text-slate-600 dark:text-slate-300',
          )}
        >
          {value === 'write' ? 'Entries' : 'Talk'}
        </button>
      ))}
    </div>
  );
}

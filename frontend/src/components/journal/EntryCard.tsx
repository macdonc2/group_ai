import { useState } from 'react';
import { AlertCircle, Brain, CalendarPlus, Check, Loader2, Pencil, Trash2, X } from 'lucide-react';
import { useJournalStore } from '../../stores/journalStore';
import type { JournalEntry } from '../../types/journal';
import { clockTime } from './dates';

/** One saved entry: the text, its memory state, edit and delete, and any calendar suggestions. */
export function EntryCard({ entry }: { entry: JournalEntry }) {
  const timezone = useJournalStore((s) => s.timezone);
  const updateEntry = useJournalStore((s) => s.updateEntry);
  const deleteEntry = useJournalStore((s) => s.deleteEntry);
  const retryMemory = useJournalStore((s) => s.retryMemory);
  const answerSuggestion = useJournalStore((s) => s.answerSuggestion);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.body);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const save = async () => {
    if (!draft.trim()) return;
    setBusy('save');
    const ok = await updateEntry(entry.id, draft);
    setBusy(null);
    if (ok) setEditing(false);
  };

  const answer = async (suggestionId: string, choice: 'accept' | 'dismiss') => {
    setBusy(suggestionId);
    await answerSuggestion(entry.id, suggestionId, choice);
    setBusy(null);
  };

  const edited = entry.updated_at !== entry.created_at;

  return (
    <article className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 wt-card">
      <header className="flex items-center gap-2 px-4 pt-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="font-medium tabular-nums">{clockTime(entry.created_at, timezone)}</span>
        {edited && <span>· edited</span>}
        <span className="ml-auto flex items-center gap-1">
          {!editing && !confirmingDelete && (
            <>
              <button
                onClick={() => { setDraft(entry.body); setEditing(true); }}
                className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title="Edit entry"
                aria-label="Edit entry"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setConfirmingDelete(true)}
                className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                title="Delete entry"
                aria-label="Delete entry"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </span>
      </header>

      {editing ? (
        <div className="px-4 pb-3 pt-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(16, Math.max(4, draft.split('\n').length + 1))}
            autoFocus
            className="w-full resize-y rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-[15px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 text-sm rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={!draft.trim() || busy === 'save'}
              className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors wt-accent-bg"
            >
              {busy === 'save' ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : (
        <p className="px-4 py-2 text-[15px] leading-relaxed whitespace-pre-wrap break-words">{entry.body}</p>
      )}

      {confirmingDelete && (
        <div className="mx-4 mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-800 dark:text-red-200">
          <span className="flex-1 min-w-40">Delete this entry? What the assistant already learned from it (people, places, preferences) stays in memory.</span>
          <button
            onClick={() => setConfirmingDelete(false)}
            className="px-2.5 py-1 rounded hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors"
          >
            Keep
          </button>
          <button
            onClick={() => deleteEntry(entry.id)}
            className="px-2.5 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors"
          >
            Delete
          </button>
        </div>
      )}

      {entry.suggestions.length > 0 && !editing && (
        <ul className="px-4 pb-3 space-y-1.5">
          {entry.suggestions.map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm"
            >
              <CalendarPlus className="w-4 h-4 shrink-0 text-blue-500" />
              <span className="flex-1 min-w-40">
                <span className="font-medium">{s.title}</span>
                <span className="text-slate-500 dark:text-slate-400"> · {s.when}{s.location ? ` · ${s.location}` : ''}</span>
              </span>
              {s.status === 'added' ? (
                <span className="inline-flex items-center gap-1 text-xs text-green-700 dark:text-green-400">
                  <Check className="w-3.5 h-3.5" /> On your calendar
                </span>
              ) : (
                <>
                  <button
                    onClick={() => answer(s.id, 'accept')}
                    disabled={busy === s.id}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors wt-accent-bg"
                  >
                    {busy === s.id && <Loader2 className="w-3 h-3 animate-spin" />}
                    Add to calendar
                  </button>
                  <button
                    onClick={() => answer(s.id, 'dismiss')}
                    disabled={busy === s.id}
                    className="p-1 rounded text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                    title="Dismiss"
                    aria-label={`Dismiss suggestion: ${s.title}`}
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <footer className="px-4 pb-3 text-xs text-slate-400 dark:text-slate-500 flex items-center gap-1.5">
        {entry.memory_status === 'pending' && (
          <><Loader2 className="w-3 h-3 animate-spin" /> Adding to memory…</>
        )}
        {entry.memory_status === 'done' && (
          <><Brain className="w-3 h-3" /> In memory</>
        )}
        {entry.memory_status === 'skipped' && (
          <><Brain className="w-3 h-3" /> Saved (memory is not available on this server)</>
        )}
        {entry.memory_status === 'failed' && (
          <span className="inline-flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
            <AlertCircle className="w-3 h-3" /> Saved, but not all of it reached memory.
            <button onClick={() => retryMemory(entry.id)} className="underline hover:no-underline">Retry</button>
          </span>
        )}
      </footer>
    </article>
  );
}

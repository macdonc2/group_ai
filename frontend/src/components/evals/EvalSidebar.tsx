import { useState } from 'react';
import { Play, RefreshCw, MessageSquare, ListChecks } from 'lucide-react';
import { cn, formatTimestamp, truncate } from '../../lib/utils';
import { useEvalStore } from '../../stores/evalStore';
import { StatusBadge } from './EvalRunView';

function NewRunForm() {
  const { suites, startRun } = useEvalStore();
  const [picked, setSuite] = useState('');
  const [judge, setJudge] = useState('openai');
  const [repeats, setRepeats] = useState(1);
  const [busy, setBusy] = useState(false);
  const suite = picked || suites[0]?.name || '';
  const s = suites.find((x) => x.name === suite);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await startRun({ suite, judge, repeats });
        setBusy(false);
      }}
      className="p-3 space-y-2 border-b border-slate-200 dark:border-slate-700 text-xs"
    >
      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-2 flex flex-col gap-0.5">
          <span className="text-slate-500">Suite</span>
          <select value={suite} onChange={(e) => setSuite(e.target.value)} className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1">
            {suites.map((x) => <option key={x.name} value={x.name}>{x.name} ({x.cases.length})</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-slate-500">Judge</span>
          <select value={judge} onChange={(e) => setJudge(e.target.value)} className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1">
            <option value="openai">OpenAI</option>
            <option value="jev">Jev</option>
            <option value="both">Both (agreement)</option>
            <option value="none">None</option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-slate-500">Repeats</span>
          <input type="number" min={1} max={5} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1" />
        </label>
      </div>
      {s && <p className="text-[11px] text-slate-500 leading-snug">{s.description}</p>}
      <button disabled={busy || !suite} className="w-full inline-flex items-center justify-center gap-1.5 rounded bg-blue-600 text-white py-1.5 hover:bg-blue-700 disabled:opacity-50">
        <Play size={13} /> {busy ? 'Starting…' : 'Run suite'}
      </button>
      <p className="text-[10px] text-slate-400 leading-snug">Runs real model calls against throwaway seeded users (removed afterwards).</p>
    </form>
  );
}

export function EvalSidebar({ onSelect }: { onSelect?: () => void }) {
  const { mode, setMode, runs, selectedRunId, selectRun, refreshRuns, error } = useEvalStore();
  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-slate-200 dark:border-slate-700 text-xs">
        {([['runs', 'Eval runs', ListChecks], ['conversations', 'Conversations', MessageSquare]] as const).map(([m, label, Icon]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn('flex-1 flex items-center justify-center gap-1 py-2', mode === m ? 'text-blue-600 dark:text-blue-400 font-medium bg-white dark:bg-slate-900' : 'text-slate-500')}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>
      {error && <p className="px-3 py-2 text-[11px] text-red-600 dark:text-red-400 break-words">{truncate(error, 200)}</p>}
      {mode === 'runs' ? (
        <>
          <NewRunForm />
          <div className="flex items-center justify-between px-3 pt-2 text-xs text-slate-500">
            <span>History</span>
            <button onClick={() => refreshRuns()} className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700" title="Refresh"><RefreshCw size={12} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {runs.length === 0 && <p className="text-center text-xs text-slate-500 py-6">No runs yet</p>}
            {runs.map((r) => {
              const active = r.id === selectedRunId;
              return (
                <button
                  key={r.id}
                  onClick={() => { selectRun(r.id); onSelect?.(); }}
                  className={cn('w-full text-left p-2.5 rounded-lg transition-colors', active ? 'bg-blue-600 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800')}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{r.suite}</span>
                    <span className="font-mono text-sm">{r.pass_rate == null ? '' : `${Math.round(r.pass_rate * 100)}%`}</span>
                  </div>
                  <div className={cn('flex items-center gap-2 text-[11px] mt-0.5', active ? 'opacity-85' : 'text-slate-500 dark:text-slate-400')}>
                    {active ? <span>{r.status}</span> : <StatusBadge status={r.status} />}
                    <span>· {r.judge}</span>
                    {r.status === 'running' && r.total ? <span>· {r.done ?? 0}/{r.total}</span> : null}
                    {r.started_at && <span className="ml-auto">{formatTimestamp(new Date(r.started_at + 'Z'))}</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </>
      ) : (
        <ConversationPicker onSelect={onSelect} />
      )}
    </div>
  );
}

function ConversationPicker({ onSelect }: { onSelect?: () => void }) {
  const { conversations, selectedConversationId, selectConversation, evalSelection, toggleEvalSelection, setEvalSelection, evaluateSelected } = useEvalStore();
  const [judge, setJudge] = useState('openai');
  const [busy, setBusy] = useState(false);
  const allOn = conversations.length > 0 && evalSelection.length === conversations.length;
  return (
    <>
      <div className="flex items-center justify-between px-3 pt-2 text-xs text-slate-500">
        <label className="inline-flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={allOn}
            onChange={() => setEvalSelection(allOn ? [] : conversations.slice(0, 50).map((c) => c.conversation_id))}
          />
          Select for eval
        </label>
        <span>{conversations.length} conversations</span>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {conversations.length === 0 && <p className="text-center text-xs text-slate-500 py-6 px-3">No conversations yet.</p>}
        {conversations.map((c) => {
          const active = c.conversation_id === selectedConversationId;
          const ticked = evalSelection.includes(c.conversation_id);
          return (
            <div
              key={c.conversation_id}
              className={cn('flex items-start gap-2 p-2.5 rounded-lg', active ? 'bg-blue-600 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800')}
            >
              <input
                type="checkbox"
                className="mt-1 shrink-0"
                checked={ticked}
                onChange={() => toggleEvalSelection(c.conversation_id)}
                aria-label={`Select ${c.title ?? 'conversation'} for evaluation`}
              />
              <button className="flex-1 min-w-0 text-left" onClick={() => { selectConversation(c.conversation_id); onSelect?.(); }}>
                <div className="text-sm font-medium truncate">{c.title || 'Untitled conversation'}</div>
                <div className={cn('text-[11px] mt-0.5', active ? 'opacity-85' : 'text-slate-500')}>
                  {Math.ceil(c.messages / 2)} turns · {c.traced_turns ? `${c.traced_turns} traced` : 'transcript only'} · {formatTimestamp(new Date(c.last_at + 'Z'))}
                </div>
              </button>
            </div>
          );
        })}
      </div>
      <div className="border-t border-slate-200 dark:border-slate-700 p-3 space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <select value={judge} onChange={(e) => setJudge(e.target.value)} className="flex-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1">
            <option value="openai">OpenAI judge</option>
            <option value="jev">Jev judge</option>
            <option value="both">Both (agreement)</option>
          </select>
          <button
            disabled={!evalSelection.length || busy}
            onClick={async () => { setBusy(true); await evaluateSelected(judge); setBusy(false); }}
            className="inline-flex items-center gap-1.5 rounded bg-blue-600 text-white px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50"
          >
            <Play size={13} /> {busy ? 'Starting…' : `Evaluate ${evalSelection.length || ''}`.trim()}
          </button>
        </div>
        <p className="text-[10px] text-slate-400 leading-snug">
          Judges flow, task completion and memory use. Turns from before tracing are judged on the transcript alone.
        </p>
      </div>
    </>
  );
}

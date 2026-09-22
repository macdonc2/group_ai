import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '../../lib/utils';
import { useEvalStore } from '../../stores/evalStore';
import type { TurnTrace } from '../../types';
import { PredicateTree } from './PredicateTree';
import { TraceInspector } from './TraceInspector';
import { fmtMs, fmtUsd } from './treeModel';

export interface ViewerTurn {
  user: string;
  response: string | null;
  trace?: TurnTrace;
}

/** Turn picker + predicate tree + inspector for one conversation (eval case or real traffic). */
export function TraceViewer({ turns, expect }: { turns: ViewerTurn[]; expect?: { route?: string[] | null; forbid_nodes?: string[] } | null }) {
  const topology = useEvalStore((s) => s.topology);
  const [turnIdx, setTurnIdx] = useState(Math.max(turns.length - 1, 0));
  const [seq, setSeq] = useState<number | null>(null);
  const idx = Math.min(turnIdx, turns.length - 1);
  const turn = turns[idx];
  const isLast = idx === turns.length - 1;

  if (!turn) return <div className="p-4 text-sm text-slate-500">No turns recorded.</div>;

  return (
    <div className="flex flex-col h-full min-h-0">
      {turns.length > 1 && (
        <div className="flex gap-1 px-3 pt-2 overflow-x-auto shrink-0">
          {turns.map((t, i) => (
            <button
              key={i}
              onClick={() => { setTurnIdx(i); setSeq(null); }}
              className={cn(
                'px-2.5 py-1 rounded-t text-xs whitespace-nowrap border-b-2',
                i === idx ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-medium' : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-200',
              )}
              title={t.user}
            >
              Turn {i + 1}
              {t.trace && <span className="ml-1 text-[10px] text-slate-400">{fmtMs(t.trace.total_ms)}</span>}
            </button>
          ))}
        </div>
      )}
      <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-700 text-xs space-y-1 shrink-0 max-h-44 overflow-y-auto">
        <div><span className="font-semibold text-slate-500">User:</span> {turn.user}</div>
        <details>
          <summary className="cursor-pointer text-slate-500">
            <span className="font-semibold">Assistant</span>
            {turn.trace && <span className="ml-2 text-slate-400">{fmtMs(turn.trace.total_ms)} · {fmtUsd(turn.trace.usage.cost_usd)}</span>}
          </summary>
          <div className="prose prose-sm dark:prose-invert max-w-none mt-1 text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.response ?? ''}</ReactMarkdown>
          </div>
        </details>
      </div>
      {turn.trace ? (
        <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
          <div className="flex-1 min-h-[360px] lg:min-h-0 border-b lg:border-b-0 lg:border-r border-slate-200 dark:border-slate-700">
            <PredicateTree
              trace={turn.trace}
              topology={topology}
              expect={isLast ? expect : null}
              selectedSeq={seq}
              onSelect={setSeq}
            />
          </div>
          <div className="lg:w-96 shrink-0 min-h-0 max-h-[60vh] lg:max-h-none">
            <TraceInspector trace={turn.trace} selectedSeq={seq} onSelect={setSeq} />
          </div>
        </div>
      ) : (
        <div className="p-4 text-sm text-slate-500">This turn has no trace.</div>
      )}
    </div>
  );
}

import { useState } from 'react';
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useEvalStore } from '../../stores/evalStore';
import { TraceViewer } from './TraceViewer';
import { fmtMs, fmtUsd } from './treeModel';

type Tab = 'tree' | 'scores' | 'memory';

export function CaseDetail({ onBack }: { onBack: () => void }) {
  const detail = useEvalStore((s) => s.caseDetail);
  const [tab, setTab] = useState<Tab>('tree');
  if (!detail) return <div className="flex-1 flex items-center justify-center"><Loader2 className="animate-spin text-slate-400" /></div>;
  const expect = detail.case.expect ?? null;
  const isResearch = !!detail.turns[0]?.research;
  const isConversation = (detail.case as { source?: string }).source === 'conversation';

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 flex flex-wrap items-center gap-2 shrink-0">
        <button onClick={onBack} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700" title="Back to run"><ArrowLeft size={16} /></button>
        <span className="font-mono text-sm font-semibold">{detail.case_id}{detail.repeat ? ` #${detail.repeat}` : ''}</span>
        {detail.passed ? (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400"><CheckCircle2 size={13} /> pass</span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-400"><XCircle size={13} /> fail</span>
        )}
        {detail.failure_tags.map((t) => (
          <span key={t} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-[10px] font-mono">{t}</span>
        ))}
        <span className="ml-auto text-xs text-slate-500 font-mono">
          {fmtMs(detail.total_ms)} · system {fmtUsd(detail.cost_usd)} · judge {fmtUsd(detail.judge_cost_usd)}
        </span>
      </div>
      {detail.case.description && <p className="px-4 pt-2 text-xs text-slate-500">{detail.case.description}</p>}
      <div className="flex gap-1 px-4 pt-2 shrink-0">
        {(['tree', 'scores', 'memory'] as Tab[]).filter((t) => !((isResearch || isConversation) && t === 'memory')).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn('px-3 py-1 text-xs rounded-t border-b-2', tab === t ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-medium' : 'border-transparent text-slate-500')}
          >
            {t === 'tree' ? (isResearch ? 'Report & sources' : 'Predicate tree') : t === 'scores' ? 'Scores & judges' : 'Seed & knowledge graph'}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 border-t border-slate-200 dark:border-slate-700 flex flex-col">
        {tab === 'tree' && (isResearch ? <ResearchTurn /> : <TraceViewer turns={detail.turns} expect={expect} />)}
        {tab === 'scores' && <Scores />}
        {tab === 'memory' && <Memory />}
      </div>
    </div>
  );
}

function Scores() {
  const d = useEvalStore((s) => s.caseDetail)!;
  return (
    <div className="overflow-y-auto p-4 space-y-4 text-xs">
      {d.error && <p className="text-red-600 dark:text-red-400">{d.error}</p>}
      <section>
        <h4 className="font-semibold mb-2">Deterministic checks</h4>
        <div className="space-y-2">
          {Object.values(d.scores).map((s) => (
            <div key={s.name} className="rounded border border-slate-200 dark:border-slate-700 p-2">
              <div className="flex items-center gap-2">
                {s.passed ? <CheckCircle2 size={13} className="text-emerald-600" /> : <XCircle size={13} className="text-red-600" />}
                <span className="font-mono font-semibold">{s.name}</span>
                <span className="font-mono text-slate-500">{s.score}</span>
                {!s.passed && <span className="text-[10px] text-slate-500">→ {s.tag}</span>}
              </div>
              <pre className="mt-1 text-[10px] whitespace-pre-wrap text-slate-600 dark:text-slate-300">{JSON.stringify(s.detail, null, 2)}</pre>
            </div>
          ))}
          {!Object.keys(d.scores).length && <p className="text-slate-500">No deterministic checks for this case.</p>}
        </div>
      </section>
      {Object.entries(d.judgements).map(([judge, rubrics]) => (
        <section key={judge}>
          <h4 className="font-semibold mb-2">Judge: {judge}</h4>
          <div className="space-y-2">
            {Object.entries(rubrics).map(([rname, r]) => (
              <div key={rname} className="rounded border border-slate-200 dark:border-slate-700 p-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold">{rname}</span>
                  <span className="font-mono text-slate-500">mean {r.mean?.toFixed(2) ?? '–'}</span>
                  {r.error && <span className="text-red-600">{r.error}</span>}
                </div>
                {r.summary && <p className="text-slate-600 dark:text-slate-300 mb-1">{r.summary}</p>}
                <table className="w-full">
                  <tbody>
                    {Object.entries(r.dimensions ?? {}).map(([dim, v]) => (
                      <tr key={dim} className="border-t border-slate-100 dark:border-slate-700/60 align-top">
                        <td className="py-1 pr-2 font-mono text-[11px] w-40">{dim}</td>
                        <td className={cn('py-1 pr-2 font-mono w-6 text-right', v.score != null && v.score <= 2 && 'text-red-600 dark:text-red-400 font-semibold')}>{v.score ?? '–'}</td>
                        <td className="py-1 text-slate-600 dark:text-slate-300">{v.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </section>
      ))}
      {d.case.expect?.answer_criteria && (
        <section>
          <h4 className="font-semibold mb-1">Answer criteria</h4>
          <p className="text-slate-600 dark:text-slate-300">{d.case.expect.answer_criteria}</p>
        </section>
      )}
    </div>
  );
}

function Memory() {
  const d = useEvalStore((s) => s.caseDetail)!;
  return (
    <div className="overflow-y-auto p-4 grid lg:grid-cols-2 gap-4 text-xs">
      <section>
        <h4 className="font-semibold mb-2">Seeded before the run</h4>
        <pre className="text-[10px] whitespace-pre-wrap bg-slate-50 dark:bg-slate-900 rounded p-2">{JSON.stringify(d.case.seed, null, 2)}</pre>
        <h4 className="font-semibold my-2">Expectations</h4>
        <pre className="text-[10px] whitespace-pre-wrap bg-slate-50 dark:bg-slate-900 rounded p-2">{JSON.stringify(d.case.expect, null, 2)}</pre>
      </section>
      <section>
        <h4 className="font-semibold mb-2">Social graph after the run</h4>
        {d.entity_snapshot ? (
          Object.entries(d.entity_snapshot).map(([type, nodes]) => (
            <div key={type} className="mb-3">
              <div className="font-medium capitalize mb-1">{type} ({nodes.length})</div>
              {nodes.map((n, i) => (
                <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-1.5 mb-1">
                  <span className="font-semibold">{String(n.name)}</span>
                  {Array.isArray(n.aliases) && n.aliases.length > 0 && <span className="text-slate-500"> aka {(n.aliases as string[]).join(', ')}</span>}
                  {(n.relationship_type || n.species) ? <span className="text-slate-500"> · {String(n.relationship_type ?? n.species)}</span> : null}
                </div>
              ))}
            </div>
          ))
        ) : (
          <p className="text-slate-500">This case didn't assert graph state, so no snapshot was taken.</p>
        )}
      </section>
    </div>
  );
}

function ResearchTurn() {
  const d = useEvalStore((s) => s.caseDetail)!;
  const t = d.turns[0];
  const sources = (t.research?.sources ?? []) as { id: string; ref?: number; lane: string; title: string; url?: string }[];
  return (
    <div className="overflow-y-auto p-4 grid lg:grid-cols-[1fr_22rem] gap-4 text-xs">
      <pre className="whitespace-pre-wrap text-[11px] bg-slate-50 dark:bg-slate-900 rounded p-3">{t.response}</pre>
      <div>
        <h4 className="font-semibold mb-2">Sources ({sources.length})</h4>
        <ol className="space-y-1">
          {sources.map((s) => (
            <li key={s.id}>
              <span className="font-mono text-slate-400">[{s.ref ?? s.id}]</span> <span className="text-slate-500">{s.lane}</span>{' '}
              {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">{s.title}</a> : s.title}
            </li>
          ))}
        </ol>
        <h4 className="font-semibold my-2">Usage</h4>
        <pre className="text-[10px] whitespace-pre-wrap bg-slate-50 dark:bg-slate-900 rounded p-2">{JSON.stringify(t.research?.usage, null, 2)}</pre>
      </div>
    </div>
  );
}

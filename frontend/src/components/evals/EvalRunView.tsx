import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertTriangle, CheckCircle2, Loader2, XCircle, GitCompare } from 'lucide-react';
import { api } from '../../lib/api';
import { cn } from '../../lib/utils';
import { useEvalStore } from '../../stores/evalStore';
import type { EvalSummary, RunComparison } from '../../types';
import { fmtMs, fmtTokens, fmtUsd } from './treeModel';

function Card({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 p-4', className)}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-3">{title}</h3>
      {children}
    </section>
  );
}

/** A single-hue magnitude bar (0..max) with the value in text ink beside it. */
function Meter({ value, max = 1, label, display }: { value: number | null | undefined; max?: number; label: string; display?: string }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="flex items-center gap-2 text-xs" title={`${label}: ${display ?? value ?? '–'}`}>
      <span className="w-44 shrink-0 truncate text-slate-600 dark:text-slate-300 font-mono text-[11px]">{label}</span>
      <span className="flex-1 h-2 bg-slate-100 dark:bg-slate-700/60 rounded-full overflow-hidden">
        <span className="block h-2 rounded-full bg-blue-500" style={{ width: `${pct}%` }} />
      </span>
      <span className="w-12 text-right font-mono text-slate-800 dark:text-slate-100">{display ?? (value == null ? '–' : value.toFixed(2))}</span>
    </div>
  );
}

function Headline({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-3 bg-white dark:bg-slate-800/40">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className="text-2xl font-semibold text-slate-900 dark:text-slate-100 font-mono">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

function JudgeTable({ summary }: { summary: EvalSummary }) {
  const judges = Object.keys(summary.judge ?? {});
  const dims = Array.from(new Set(judges.flatMap((j) => Object.keys(summary.judge[j])))).sort();
  if (!dims.length) return <p className="text-xs text-slate-500">No judge scores for this run.</p>;
  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-500 dark:text-slate-400">
            <th className="font-medium py-1">rubric.dimension</th>
            {judges.map((j) => <th key={j} className="font-medium py-1 text-right w-40">{j} (1–5)</th>)}
          </tr>
        </thead>
        <tbody>
          {dims.map((d) => (
            <tr key={d} className="border-t border-slate-100 dark:border-slate-700/60">
              <td className="py-1 font-mono text-[11px] text-slate-700 dark:text-slate-300">{d}</td>
              {judges.map((j) => {
                const v = summary.judge[j][d];
                return (
                  <td key={j} className="py-1">
                    <div className="flex items-center justify-end gap-2" title={`${j} · ${d}: ${v ?? '–'}`}>
                      <span className="w-20 h-1.5 bg-slate-100 dark:bg-slate-700/60 rounded-full overflow-hidden">
                        <span className="block h-1.5 rounded-full bg-blue-500" style={{ width: `${v == null ? 0 : ((v - 1) / 4) * 100}%` }} />
                      </span>
                      <span className="font-mono w-8 text-right text-slate-800 dark:text-slate-100">{v?.toFixed(2) ?? '–'}</span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {summary.agreement && summary.agreement.n > 0 && (
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
          Judge agreement ({summary.agreement.judges.join(' vs ')}, n={summary.agreement.n}):{' '}
          exact <b>{pct(summary.agreement.exact)}</b>, within ±1 <b>{pct(summary.agreement.within_1)}</b>,
          weighted κ <b>{summary.agreement.weighted_kappa?.toFixed(2) ?? '–'}</b>
        </p>
      )}
    </div>
  );
}

const pct = (v: number | null | undefined) => (v == null ? '–' : `${Math.round(v * 100)}%`);

function CompareCard({ runId }: { runId: string }) {
  const { runs, run, compareWith, setCompareWith } = useEvalStore();
  const [fetched, setFetched] = useState<{ key: string; data: RunComparison | null } | null>(null);
  const candidates = runs.filter((r) => r.id !== runId && r.suite === run?.suite && r.status === 'complete');
  const key = compareWith ? `${compareWith}:${runId}` : null;
  useEffect(() => {
    if (!compareWith) return;
    const k = `${compareWith}:${runId}`;
    api.evals.compare(compareWith, runId)
      .then((data) => setFetched({ key: k, data }))
      .catch(() => setFetched({ key: k, data: null }));
  }, [compareWith, runId]);
  const cmp = key && fetched?.key === key ? fetched.data : null;
  return (
    <Card title="Compare with an earlier run">
      <select
        value={compareWith ?? ''}
        onChange={(e) => setCompareWith(e.target.value || null)}
        className="text-xs rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1"
      >
        <option value="">— choose a baseline —</option>
        {candidates.map((r) => (
          <option key={r.id} value={r.id}>
            {r.started_at?.slice(0, 16).replace('T', ' ')} · {r.judge} · {pct(r.pass_rate)} {r.git_sha ? `· ${r.git_sha.slice(0, 7)}` : ''}
          </option>
        ))}
      </select>
      {cmp && (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400"><XCircle size={13} /> Regressions: {cmp.regressions.join(', ') || 'none'}</span>
            <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400"><CheckCircle2 size={13} /> Fixed: {cmp.fixes.join(', ') || 'none'}</span>
          </div>
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1 font-medium">metric</th><th className="text-right font-medium">baseline</th><th className="text-right font-medium">this run</th><th className="text-right font-medium">Δ</th></tr></thead>
            <tbody>
              {cmp.metrics.filter((m) => m.a != null || m.b != null).map((m) => (
                <tr key={m.metric} className="border-t border-slate-100 dark:border-slate-700/60">
                  <td className="py-0.5 font-mono text-[11px]">{m.metric}</td>
                  <td className="text-right font-mono">{m.a ?? '–'}</td>
                  <td className="text-right font-mono">{m.b ?? '–'}</td>
                  <td className="text-right font-mono">{m.delta == null ? '–' : `${m.delta > 0 ? '▲' : m.delta < 0 ? '▼' : ''} ${Math.abs(m.delta)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function EvalRunView({ onOpenCase }: { onOpenCase: (id: string) => void }) {
  const { run, cases, loading, refreshRuns } = useEvalStore();
  const [tag, setTag] = useState<string | null>(null);
  const [onlyFailed, setOnlyFailed] = useState(false);

  // Poll while the run is live
  useEffect(() => {
    if (!run || run.status !== 'running') return;
    const t = setInterval(() => refreshRuns(), 4000);
    return () => clearInterval(t);
  }, [run, refreshRuns]);

  const shown = useMemo(
    () => cases.filter((c) => (!onlyFailed || !c.passed) && (!tag || c.failure_tags.some((t) => t === tag || t.startsWith(`${tag}.`)))),
    [cases, tag, onlyFailed],
  );

  if (loading && !run) return <div className="flex-1 flex items-center justify-center"><Loader2 className="animate-spin text-slate-400" /></div>;
  if (!run) return null;
  const s = run.summary as EvalSummary;
  const hasSummary = s && 'cases' in s;
  const byNode = hasSummary ? Object.entries(s.latency.by_node).sort((a, b) => (b[1].p95 ?? 0) - (a[1].p95 ?? 0)) : [];
  const maxP95 = Math.max(1, ...byNode.map(([, v]) => v.p95 ?? 0));

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{run.suite}</h2>
          <StatusBadge status={run.status} />
          <span className="text-xs text-slate-500">judge: {run.judge}</span>
          {run.git_sha && <span className="text-xs font-mono text-slate-500">{run.git_sha.slice(0, 7)}</span>}
          <span className="text-xs text-slate-500">{run.started_at?.replace('T', ' ').slice(0, 19)}</span>
          {run.status === 'running' && (
            <span className="text-xs text-slate-500">{run.done ?? 0}/{run.total ?? '?'} cases</span>
          )}
        </div>
        {run.error && <p className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1"><AlertTriangle size={14} /> {run.error}</p>}

        {hasSummary && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Headline label="Pass rate" value={pct(s.pass_rate)} sub={`${s.passed} of ${s.cases} case runs`} />
              <Headline label="Turn latency p50" value={fmtMs(s.latency.turn_p50_ms)} sub={`p95 ${fmtMs(s.latency.turn_p95_ms)}`} />
              <Headline
                label={s.cost.unpriced_calls ? 'Cost / case (lower bound)' : 'Cost / case'}
                value={fmtUsd(s.cost.per_case_usd)}
                sub={`run ${fmtUsd(s.cost.system_usd)} · judge ${fmtUsd(s.cost.judge_usd)}`}
              />
              <Headline label="Tokens" value={fmtTokens(s.cost.tokens.input + s.cost.tokens.output)} sub={`${fmtTokens(s.cost.tokens.input)} in · ${fmtTokens(s.cost.tokens.output)} out`} />
            </div>
            {(s.cost.unpriced_calls || s.cost.judge_unpriced_calls) ? (
              <p className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
                <AlertTriangle size={13} /> {s.cost.unpriced_calls ?? 0} system and {s.cost.judge_unpriced_calls ?? 0} judge LLM calls used models
                without a known price, so costs are lower bounds. Set MODEL_PRICING_JSON to include them.
              </p>
            ) : null}

            <div className="grid lg:grid-cols-2 gap-4">
              <Card title="Deterministic checks (mean, 0–1)">
                <div className="space-y-1.5">
                  {Object.entries(s.deterministic).map(([k, v]) => <Meter key={k} label={k} value={v} />)}
                  {!Object.keys(s.deterministic).length && <p className="text-xs text-slate-500">None asserted.</p>}
                </div>
              </Card>
              <Card title="LLM judge (mean score per dimension)">
                <JudgeTable summary={s} />
              </Card>
              <Card title="Node latency p95 (p50 in tooltip)">
                <div className="space-y-1.5">
                  {byNode.map(([node, v]) => (
                    <Meter key={node} label={`${node} (n=${v.n})`} value={v.p95} max={maxP95} display={fmtMs(v.p95)} />
                  ))}
                </div>
              </Card>
              <Card title="Failure categories">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(s.failure_counts).map(([t, n]) => (
                    <button
                      key={t}
                      onClick={() => setTag(tag === t ? null : t)}
                      className={cn(
                        'px-2 py-0.5 rounded-full text-[11px] border',
                        tag === t ? 'bg-blue-600 text-white border-blue-600' : 'border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700',
                      )}
                    >
                      {t} <span className="opacity-70">{n}</span>
                    </button>
                  ))}
                  {!Object.keys(s.failure_counts).length && <p className="text-xs text-slate-500">No failures.</p>}
                </div>
                {s.flag_counts && Object.keys(s.flag_counts).length > 0 && (
                  <div className="mt-3">
                    <div className="text-[11px] text-slate-500 mb-1">Flags on passing cases (a judge dimension ≤ 2)</div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(s.flag_counts).map(([t, n]) => (
                        <button key={t} onClick={() => setTag(tag === t ? null : t)}
                          className={cn('px-2 py-0.5 rounded-full text-[11px] border border-dashed', tag === t ? 'bg-blue-600 text-white border-blue-600' : 'border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300')}>
                          {t} <span className="opacity-70">{n}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </div>
          </>
        )}

        <Card title={`Cases (${shown.length}${shown.length !== cases.length ? ` of ${cases.length}` : ''})`}>
          <div className="flex items-center gap-3 mb-2 text-xs">
            <label className="inline-flex items-center gap-1"><input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} /> failed only</label>
            {tag && <button onClick={() => setTag(null)} className="text-blue-600 dark:text-blue-400 hover:underline">clear “{tag}”</button>}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 dark:text-slate-400">
                  <th className="py-1 font-medium w-16">result</th>
                  <th className="py-1 font-medium">case</th>
                  <th className="py-1 font-medium">failures</th>
                  <th className="py-1 font-medium text-right">judge</th>
                  <th className="py-1 font-medium text-right">latency</th>
                  <th className="py-1 font-medium text-right">cost</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => (
                  <tr key={c.id} onClick={() => onOpenCase(c.id)} className="border-t border-slate-100 dark:border-slate-700/60 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800">
                    <td className="py-1.5">
                      {c.passed ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400"><CheckCircle2 size={13} /> pass</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-700 dark:text-red-400"><XCircle size={13} /> fail</span>
                      )}
                    </td>
                    <td className="py-1.5">
                      <div className="font-mono text-[11px] text-slate-800 dark:text-slate-100">{c.case_id}{c.repeat ? ` #${c.repeat}` : ''}</div>
                      <div className="text-slate-500 truncate max-w-md">{c.user}</div>
                    </td>
                    <td className="py-1.5 text-[11px] text-slate-600 dark:text-slate-300">{c.failure_tags.join(', ')}</td>
                    <td className="py-1.5 text-right font-mono">
                      {Object.entries(c.judge_means).map(([j, v]) => <div key={j} title={j}>{v?.toFixed(1) ?? '–'}</div>)}
                    </td>
                    <td className="py-1.5 text-right font-mono">{fmtMs(c.total_ms)}</td>
                    <td className="py-1.5 text-right font-mono">{fmtUsd(c.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {run.failure_analysis_md && (
          <Card title="Failure analysis">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{run.failure_analysis_md}</ReactMarkdown>
            </div>
          </Card>
        )}

        {run.status === 'complete' && <CompareCard runId={run.id} />}
        <p className="text-[11px] text-slate-400 flex items-center gap-1"><GitCompare size={11} /> Run config: {JSON.stringify(run.config)}</p>
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  if (status === 'running') return <span className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400"><Loader2 size={12} className="animate-spin" /> running</span>;
  if (status === 'complete') return <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400"><CheckCircle2 size={12} /> complete</span>;
  return <span className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-400"><XCircle size={12} /> {status}</span>;
}

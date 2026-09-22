import { useState } from 'react';
import { ChevronRight, Check, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { TurnTrace } from '../../types';
import { fmtMs, fmtTokens, fmtUsd } from './treeModel';

function Section({ title, count, children, defaultOpen = true }: { title: string; count?: number; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-slate-200 dark:border-slate-700">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-1 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800">
        <ChevronRight size={12} className={cn('transition-transform', open && 'rotate-90')} />
        {title}
        {count != null && <span className="ml-auto font-normal text-slate-400">{count}</span>}
      </button>
      {open && <div className="px-3 pb-3 space-y-2">{children}</div>}
    </div>
  );
}

function Pre({ text }: { text: unknown }) {
  const s = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  return (
    <pre className="text-[10px] leading-4 whitespace-pre-wrap break-words bg-slate-50 dark:bg-slate-900 rounded p-2 max-h-48 overflow-auto text-slate-700 dark:text-slate-300">
      {s}
    </pre>
  );
}

function Waterfall({ trace, onSelect, selectedSeq }: { trace: TurnTrace; onSelect: (seq: number) => void; selectedSeq: number | null }) {
  const total = trace.total_ms || Math.max(1, ...trace.spans.map((s) => s.end_ms ?? s.start_ms));
  return (
    <div className="space-y-0.5">
      {trace.spans.map((s) => {
        const left = (s.start_ms / total) * 100;
        const width = Math.max(((s.duration_ms ?? 0) / total) * 100, 0.8);
        return (
          <button
            key={s.seq}
            onClick={() => onSelect(s.seq)}
            className={cn('w-full flex items-center gap-2 text-[10px] rounded px-1 hover:bg-slate-100 dark:hover:bg-slate-800', selectedSeq === s.seq && 'bg-blue-50 dark:bg-blue-950/40')}
          >
            <span className="w-28 shrink-0 truncate text-left text-slate-600 dark:text-slate-300">{s.node}</span>
            <span className="relative flex-1 h-2.5 bg-slate-100 dark:bg-slate-800 rounded">
              <span className="absolute top-0 h-2.5 rounded bg-blue-500/80" style={{ left: `${left}%`, width: `${width}%` }} />
            </span>
            <span className="w-12 shrink-0 text-right font-mono text-slate-500">{fmtMs(s.duration_ms)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function TraceInspector({ trace, selectedSeq, onSelect }: { trace: TurnTrace; selectedSeq: number | null; onSelect: (seq: number | null) => void }) {
  const span = selectedSeq != null ? trace.spans.find((s) => s.seq === selectedSeq) : null;
  const inSpan = (t: number) => !span || (t >= span.start_ms && (span.end_ms == null || t <= span.end_ms + 1));
  const bySeq = <T extends { seq: number | null }>(xs: T[]) => (span ? xs.filter((x) => x.seq === span.seq) : xs);
  const decisions = bySeq(trace.decisions);
  const events = bySeq(trace.events);
  const retrievals = bySeq(trace.retrievals);
  const tools = bySeq(trace.tool_calls);
  const llm = trace.llm_calls.filter((c) => c.role === 'system' && (!span || (c.node === span.node && inSpan(c.at_ms))));
  const u = trace.usage;

  return (
    <div className="h-full overflow-y-auto text-xs">
      <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div className="font-semibold text-slate-800 dark:text-slate-100">
          {span ? `${span.node} #${span.seq}` : 'Whole turn'}
        </div>
        {span && (
          <button onClick={() => onSelect(null)} className="text-[10px] text-blue-600 dark:text-blue-400 hover:underline">
            show turn
          </button>
        )}
      </div>

      {!span && (
        <Section title="Latency & cost">
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <Stat label="total" value={fmtMs(trace.total_ms)} />
            <Stat label="LLM calls" value={String(u.llm_calls)} />
            <Stat label="cost" value={fmtUsd(u.cost_usd)} />
            <Stat label="input tok" value={fmtTokens(u.input_tokens)} />
            <Stat label="output tok" value={fmtTokens(u.output_tokens)} />
            <Stat label="embed tok" value={fmtTokens(u.embedding_tokens)} />
          </div>
          {u.unpriced_calls > 0 && (
            <p className="text-[10px] text-amber-600 dark:text-amber-400">
              {u.unpriced_calls} call(s) unpriced — set MODEL_PRICING_JSON for these models.
            </p>
          )}
          <Waterfall trace={trace} onSelect={onSelect} selectedSeq={selectedSeq} />
        </Section>
      )}

      {span && (
        <Section title="Timing">
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <Stat label="node" value={fmtMs(span.duration_ms)} />
            <Stat label="in LLM" value={fmtMs(span.llm_ms ?? 0)} />
            <Stat label="cost" value={fmtUsd(span.cost_usd ?? (llm.length ? null : 0))} />
          </div>
        </Section>
      )}

      <Section title="Predicates" count={decisions.length}>
        {decisions.length === 0 && <Empty />}
        {decisions.map((d, i) => (
          <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2">
            <div className="flex items-center gap-1.5">
              {d.result ? <Check size={12} className="text-emerald-600" /> : <X size={12} className="text-slate-400" />}
              <span className="font-mono text-[11px] text-slate-800 dark:text-slate-100">{d.predicate}</span>
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">{d.node} → <span className="font-medium">{d.next}</span></div>
            {Object.keys(d.inputs).length > 0 && <Pre text={d.inputs} />}
          </div>
        ))}
      </Section>

      <Section title="LLM calls" count={llm.length} defaultOpen={!!span}>
        {llm.length === 0 && <Empty />}
        {llm.map((c, i) => (
          <details key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2">
            <summary className="cursor-pointer flex flex-wrap gap-x-2 text-[10px]">
              <span className="font-semibold text-slate-800 dark:text-slate-100">{c.agent}</span>
              <span className="text-slate-500">{c.model}</span>
              <span className="font-mono">{fmtTokens(c.input_tokens)}→{fmtTokens(c.output_tokens)}</span>
              <span className="font-mono">{fmtMs(c.duration_ms)}</span>
              <span>{fmtUsd(c.cost_usd)}</span>
            </summary>
            {c.input_preview && (<><div className="mt-1 text-[10px] font-semibold">Prompt</div><Pre text={c.input_preview} /></>)}
            {c.output_preview && (<><div className="mt-1 text-[10px] font-semibold">Output</div><Pre text={c.output_preview} /></>)}
          </details>
        ))}
      </Section>

      <Section title="Retrieval" count={retrievals.reduce((n, r) => n + r.hits.length, 0)} defaultOpen={retrievals.length > 0}>
        {retrievals.length === 0 && <Empty />}
        {retrievals.map((r, i) => (
          <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2">
            <div className="text-[10px]"><span className="font-semibold">{r.source}</span> <span className="text-slate-500">“{r.query}”</span></div>
            <ol className="mt-1 space-y-1">
              {r.hits.map((h, j) => (
                <li key={j} className={cn('text-[10px] flex gap-1.5', h.used_in_prompt === false && 'opacity-50')}>
                  <span className="font-mono text-slate-400 w-4 shrink-0">{j + 1}.</span>
                  {typeof h.score === 'number' && <span className="font-mono text-blue-600 dark:text-blue-400 shrink-0">{h.score.toFixed(2)}</span>}
                  <span className="text-slate-700 dark:text-slate-300 break-words">
                    {h.type && <span className="text-slate-400">[{h.type}] </span>}
                    {h.name ? `${h.name}: ` : ''}{h.content}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </Section>

      <Section title="Tool calls" count={tools.length} defaultOpen={tools.length > 0}>
        {tools.length === 0 && <Empty />}
        {tools.map((t, i) => (
          <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2">
            <div className="flex items-center gap-2 text-[10px]">
              <span className="font-semibold">{t.tool}</span>
              <span className={t.success ? 'text-emerald-600' : 'text-red-600'}>{t.success ? 'ok' : 'failed'}</span>
              <span className="font-mono text-slate-500">{fmtMs(t.duration_ms)}</span>
            </div>
            <Pre text={t.arguments} />
            <Pre text={t.result ?? ''} />
          </div>
        ))}
      </Section>

      <Section title="Events" count={events.length} defaultOpen={false}>
        {events.map((e, i) => (
          <div key={i} className="text-[10px]">
            <span className="font-mono text-slate-400">{fmtMs(e.t_ms)}</span> <span className="font-semibold">{e.type}</span>{' '}
            <span className="text-slate-500">{e.node}</span> — {e.message}
          </div>
        ))}
      </Section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 dark:bg-slate-900 px-2 py-1">
      <div className="text-slate-400">{label}</div>
      <div className="font-mono text-slate-800 dark:text-slate-100">{value}</div>
    </div>
  );
}

function Empty() {
  return <div className="text-[10px] text-slate-400">none</div>;
}

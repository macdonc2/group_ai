import { useEffect, useRef } from 'react';
import {
  GraduationCap, Wrench, BarChart3, Loader2, Check, Circle, AlertCircle,
  Search, FileText, Lightbulb, Table2, Sparkles, Image as ImageIcon, PenLine, Volume2, RefreshCw, HelpCircle,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { LANES, type LaneLog, type LaneView, type PipelineStep } from '../../stores/researchStore';
import type { LaneName } from '../../types';

const LANE_META: Record<LaneName, { label: string; blurb: string; icon: React.ReactNode }> = {
  academic: { label: 'Academic', blurb: 'arXiv · Semantic Scholar', icon: <GraduationCap className="w-4 h-4" /> },
  practical: { label: 'Practical', blurb: 'Web · docs · GitHub', icon: <Wrench className="w-4 h-4" /> },
  empirical: { label: 'Empirical', blurb: 'Numbers · benchmarks', icon: <BarChart3 className="w-4 h-4" /> },
};

const LOG_ICON: Record<LaneLog['kind'], React.ReactNode> = {
  step: <Circle className="w-3 h-3" />,
  query: <Search className="w-3 h-3" />,
  source: <FileText className="w-3 h-3" />,
  finding: <Lightbulb className="w-3 h-3" />,
  table: <Table2 className="w-3 h-3" />,
  error: <AlertCircle className="w-3 h-3" />,
  done: <Check className="w-3 h-3" />,
  round: <RefreshCw className="w-3 h-3" />,
  gap: <HelpCircle className="w-3 h-3" />,
};

function StatusBadge({ status }: { status: LaneView['status'] | PipelineStep['status'] }) {
  if (status === 'running') return <Loader2 className="w-4 h-4 animate-spin text-blue-500" />;
  if (status === 'complete') return <Check className="w-4 h-4 text-green-500" />;
  if (status === 'error') return <AlertCircle className="w-4 h-4 text-red-500" />;
  return <Circle className="w-4 h-4 text-slate-300 dark:text-slate-600" />;
}

function LaneCard({ lane, view }: { lane: LaneName; view: LaneView }) {
  const meta = LANE_META[lane];
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [view.log.length]);

  return (
    <div className={cn(
      'rounded-lg border bg-white dark:bg-slate-900 flex flex-col min-h-0',
      view.status === 'error' ? 'border-red-300 dark:border-red-800' : 'border-slate-200 dark:border-slate-700'
    )}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-200 dark:border-slate-700">
        <span className="text-slate-600 dark:text-slate-300">{meta.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium">{meta.label}</div>
          <div className="text-[11px] text-slate-400 dark:text-slate-500 truncate">{meta.blurb}</div>
        </div>
        {view.round > 1 && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300">R{view.round}</span>
        )}
        <StatusBadge status={view.status} />
      </div>
      <div className="grid grid-cols-3 gap-1 px-3 py-2 text-center text-[11px] text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-800">
        <Stat n={view.queries} label="queries" />
        <Stat n={view.sources} label="sources" />
        <Stat n={lane === 'empirical' ? view.tables : view.findings} label={lane === 'empirical' ? 'tables' : 'findings'} />
      </div>
      <div ref={logRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5 max-h-56 lg:max-h-72">
        {view.log.length === 0 ? (
          <p className="text-xs text-slate-400 dark:text-slate-500 italic">
            {view.status === 'pending' ? 'Waiting to start' : view.step || 'Working…'}
          </p>
        ) : (
          view.log.map((entry, i) => (
            <div key={i} className={cn(
              'flex items-start gap-2 text-xs leading-snug',
              entry.kind === 'error' ? 'text-red-600 dark:text-red-400'
                : entry.kind === 'finding' ? 'text-slate-800 dark:text-slate-100'
                : entry.kind === 'round' ? 'text-blue-600 dark:text-blue-300 font-medium mt-1'
                : entry.kind === 'gap' ? 'text-amber-700 dark:text-amber-300'
                : 'text-slate-500 dark:text-slate-400'
            )}>
              <span className="mt-0.5 shrink-0 opacity-70">{LOG_ICON[entry.kind]}</span>
              <span className="min-w-0 break-words">{entry.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div>
      <div className="text-base font-semibold text-slate-800 dark:text-slate-100 leading-none">{n}</div>
      <div className="mt-0.5">{label}</div>
    </div>
  );
}

const STEP_ICON: Record<PipelineStep['key'], React.ReactNode> = {
  synthesis: <Sparkles className="w-4 h-4" />,
  figures: <ImageIcon className="w-4 h-4" />,
  writer: <PenLine className="w-4 h-4" />,
  narration: <Volume2 className="w-4 h-4" />,
};

interface LaneProgressProps {
  lanes: Record<LaneName, LaneView>;
  pipeline: PipelineStep[];
  compact?: boolean;
}

export function LaneProgress({ lanes, pipeline, compact = false }: LaneProgressProps) {
  return (
    <div className="space-y-3">
      <div className={cn('grid gap-3', compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-3')}>
        {LANES.map((lane) => <LaneCard key={lane} lane={lane} view={lanes[lane]} />)}
      </div>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2">
        <div className={cn('grid gap-2', compact ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-4')}>
          {pipeline.map((step) => (
            <div key={step.key} className="flex items-center gap-2 min-w-0">
              <span className="text-slate-500 dark:text-slate-400 shrink-0">{STEP_ICON[step.key]}</span>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium">{step.label}</div>
                <div className="text-[11px] text-slate-400 dark:text-slate-500 truncate">{step.detail || '—'}</div>
              </div>
              <StatusBadge status={step.status} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

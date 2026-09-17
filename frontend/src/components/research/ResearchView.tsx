import { useState } from 'react';
import { Activity, AlertTriangle, ChevronDown, ChevronUp, ExternalLink, Loader2, RotateCcw } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useContentWidth } from '../../lib/layout';
import { useResearchStore } from '../../stores/researchStore';
import { LaneProgress } from './LaneProgress';
import { ListenButton } from './ListenButton';
import { ReportView } from './ReportView';
import { ResearchComposer } from './ResearchComposer';

interface ResearchViewProps {
  onStart: (question: string, depth: 1 | 2 | 3) => void;
  onRerun: (question: string, depth: 1 | 2 | 3) => void;
  onRefreshDetail: (id: string) => void;
}

export function ResearchView({ onStart, onRerun, onRefreshDetail }: ResearchViewProps) {
  const detail = useResearchStore((s) => s.detail);
  const lanes = useResearchStore((s) => s.lanes);
  const pipeline = useResearchStore((s) => s.pipeline);
  const draft = useResearchStore((s) => s.draft);
  const figures = useResearchStore((s) => s.figures);
  const sources = useResearchStore((s) => s.sources);
  const isStreaming = useResearchStore((s) => s.isStreaming);
  const error = useResearchStore((s) => s.error);
  const [showProgress, setShowProgress] = useState(true);
  const [showSources, setShowSources] = useState(false);
  const width = useContentWidth('research');

  if (!detail) {
    return <ResearchComposer onStart={onStart} error={error} />;
  }

  const live = ['queued', 'running', 'synthesizing', 'writing', 'narrating'].includes(detail.status) || isStreaming;
  const hasReport = draft.trim().length > 0;
  const narrating = pipeline.find((p) => p.key === 'narration')?.status === 'running';
  const failed = detail.status === 'failed' || detail.status === 'interrupted';
  const writing = pipeline.find((p) => p.key === 'writer')?.status === 'running';

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Sticky title bar */}
      <div className="border-b border-slate-200 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 backdrop-blur px-4 py-3 shrink-0">
        <div className={`${width} mx-auto flex items-start gap-3`}>
          <div className="flex-1 min-w-0">
            <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">Research question{(detail.depth ?? 1) > 1 ? ` · ${detail.depth === 3 ? 'deep' : 'standard'} depth` : ''}</p>
            <p className="text-sm sm:text-base font-medium leading-snug break-words">{detail.question}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {live && !failed && (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                {detail.progress?.phase === 'running' || pipeline.every((p) => p.status === 'pending') ? 'Researching' : pipeline.find((p) => p.status === 'running')?.label ?? 'Working'}
              </span>
            )}
            {(detail.has_audio || narrating || (hasReport && !live)) && (
              <ListenButton
                jobId={detail.id}
                hasAudio={detail.has_audio}
                generating={narrating}
                canGenerate={!live && hasReport}
                onGenerated={() => onRefreshDetail(detail.id)}
              />
            )}
            {failed && (
              <button
                onClick={() => onRerun(detail.question, ((detail.depth ?? 1) as 1 | 2 | 3))}
                className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-slate-300 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <RotateCcw className="w-4 h-4" /> Run again
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className={`${width} mx-auto px-4 py-4 space-y-4`}>
          {failed && (
            <div className="flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{detail.error || error || 'This run did not finish.'}</span>
            </div>
          )}

          {/* Progress: open while live, collapsible afterwards */}
          <section>
            <button
              onClick={() => setShowProgress((v) => !v)}
              className="w-full flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
            >
              <Activity className={cn('w-3.5 h-3.5', live && !failed && 'text-blue-500 animate-pulse')} />
              Three lanes
              <span className="ml-auto">{showProgress ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}</span>
            </button>
            {showProgress && (
              <div className="mt-2">
                <LaneProgress lanes={lanes} pipeline={pipeline} />
              </div>
            )}
          </section>

          {/* Report */}
          {hasReport ? (
            <section className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 wt-card">
              <ReportView jobId={detail.id} markdown={draft} figures={figures} sources={sources} streaming={writing} />
            </section>
          ) : live && !failed ? (
            <div className="text-center text-sm text-slate-400 dark:text-slate-500 py-8">
              The overview appears here as it is written.
            </div>
          ) : null}

          {/* Sources */}
          {sources.length > 0 && (
            <section className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 wt-card">
              <button
                onClick={() => setShowSources((v) => !v)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium"
              >
                <span>{sources.length} sources across three lanes</span>
                {showSources ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {showSources && (
                <ul className="px-4 pb-4 space-y-2 text-sm">
                  {sources.map((src) => (
                    <li key={src.id} className="flex items-start gap-2">
                      <span className="shrink-0 tabular-nums text-slate-400 dark:text-slate-500 w-6 text-right">[{src.ref}]</span>
                      <span className={cn(
                        'shrink-0 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded mt-0.5',
                        src.lane === 'academic' ? 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
                          : src.lane === 'practical' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                      )}>{src.lane}</span>
                      <span className="min-w-0 flex-1 break-words">
                        {src.url ? (
                          <a href={src.url} target="_blank" rel="noreferrer" className="hover:underline inline-flex items-center gap-1">
                            {src.title} <ExternalLink className="w-3 h-3 shrink-0 opacity-60" />
                          </a>
                        ) : src.title}
                        <span className="text-slate-400 dark:text-slate-500"> {[src.authors.slice(0, 2).join(', '), src.year, src.venue].filter(Boolean).join(' · ')}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

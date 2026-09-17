import { FlaskConical, Plus, Trash2, Loader2, Check, AlertCircle, Volume2 } from 'lucide-react';
import { cn, formatTimestamp, truncate } from '../../lib/utils';
import { useResearchStore } from '../../stores/researchStore';
import type { ResearchListItem, ResearchStatus } from '../../types';

interface ResearchListProps {
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

const LIVE: ResearchStatus[] = ['queued', 'running', 'synthesizing', 'writing', 'narrating'];

function StatusIcon({ status }: { status: ResearchStatus }) {
  if (LIVE.includes(status)) return <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />;
  if (status === 'complete') return <Check className="w-3.5 h-3.5 text-green-500" />;
  return <AlertCircle className="w-3.5 h-3.5 text-amber-500" />;
}

function statusLabel(job: ResearchListItem): string {
  if (LIVE.includes(job.status)) return job.phase === 'running' ? 'researching' : job.phase;
  return job.status;
}

export function ResearchList({ onNew, onSelect, onDelete }: ResearchListProps) {
  const jobs = useResearchStore((s) => s.jobs);
  const selectedJobId = useResearchStore((s) => s.selectedJobId);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
        <h2 className="font-semibold text-sm">Research</h2>
        <button
          onClick={onNew}
          className="p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded transition-colors"
          title="New research"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {jobs.length === 0 ? (
          <div className="text-center text-slate-500 dark:text-slate-400 text-sm py-8">
            <FlaskConical className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No research yet</p>
            <button onClick={onNew} className="mt-2 text-blue-500 hover:underline text-xs">
              Ask your first question
            </button>
          </div>
        ) : (
          <div className="space-y-1">
            {jobs.map((job) => {
              const active = job.id === selectedJobId;
              return (
                <div
                  key={job.id}
                  onClick={() => onSelect(job.id)}
                  className={cn(
                    'group flex items-start gap-2 p-3 rounded-lg cursor-pointer transition-colors',
                    active ? 'bg-blue-600 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800'
                  )}
                >
                  <div className="mt-0.5 shrink-0"><StatusIcon status={job.status} /></div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium leading-snug">
                      {truncate(job.title || job.question, 60)}
                    </p>
                    <div className={cn(
                      'flex items-center gap-2 text-xs mt-0.5',
                      active ? 'opacity-80' : 'text-slate-500 dark:text-slate-400'
                    )}>
                      <span className="capitalize">{statusLabel(job)}</span>
                      {job.has_audio && <Volume2 className="w-3 h-3" />}
                      <span>•</span>
                      <span>{formatTimestamp(new Date(job.created_at))}</span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDelete(job.id); }}
                    className={cn(
                      'p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity shrink-0',
                      active ? 'hover:bg-white/20' : 'hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-500'
                    )}
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

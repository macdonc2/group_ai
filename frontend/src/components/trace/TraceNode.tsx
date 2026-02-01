import { cn } from '../../lib/utils';
import type { TraceNode as TraceNodeType } from '../../types';
import { Check, Loader2, Circle, AlertCircle, SkipForward } from 'lucide-react';

interface TraceNodeProps {
  node: TraceNodeType;
  isLast?: boolean;
}

const STATUS_STYLES: Record<TraceNodeType['status'], { icon: React.ReactNode; className: string }> = {
  pending: {
    icon: <Circle className="w-4 h-4" />,
    className: 'text-slate-400 dark:text-slate-500',
  },
  running: {
    icon: <Loader2 className="w-4 h-4 animate-spin" />,
    className: 'text-blue-500',
  },
  complete: {
    icon: <Check className="w-4 h-4" />,
    className: 'text-green-500',
  },
  skipped: {
    icon: <SkipForward className="w-4 h-4" />,
    className: 'text-slate-400 dark:text-slate-500',
  },
  error: {
    icon: <AlertCircle className="w-4 h-4" />,
    className: 'text-red-500',
  },
};

// Friendly names for FSM nodes
const NODE_LABELS: Record<string, string> = {
  ReceiveInput: 'Receive Input',
  AnalyzeIntent: 'Analyze Intent',
  UpdateKnowledge: 'Update Knowledge',
  CheckPlan: 'Check Plan',
  CreatePlan: 'Create Plan',
  ExecutePlan: 'Execute Plan',
  SelectTool: 'Select Tool',
  ExecuteTool: 'Execute Tool',
  EvaluateResult: 'Evaluate Result',
  GenerateResponse: 'Generate Response',
  FinalizeKnowledge: 'Finalize',
};

export function TraceNode({ node, isLast }: TraceNodeProps) {
  const { icon, className } = STATUS_STYLES[node.status];
  const duration = node.startTime && node.endTime
    ? ((node.endTime - node.startTime) / 1000).toFixed(2)
    : null;
  
  return (
    <div className="relative flex items-start gap-3">
      {/* Connector line */}
      {!isLast && (
        <div className={cn(
          'absolute left-[11px] top-6 w-0.5 h-full -translate-x-1/2',
          node.status === 'complete' ? 'bg-green-200 dark:bg-green-900' : 
          node.status === 'skipped' ? 'bg-slate-200 dark:bg-slate-700' :
          'bg-slate-200 dark:bg-slate-700'
        )} />
      )}
      
      {/* Status icon */}
      <div className={cn(
        'relative z-10 shrink-0 w-6 h-6 rounded-full flex items-center justify-center',
        'bg-white dark:bg-slate-800 border-2',
        node.status === 'running' && 'border-blue-500 animate-pulse-subtle',
        node.status === 'complete' && 'border-green-500',
        node.status === 'skipped' && 'border-slate-300 dark:border-slate-600 border-dashed',
        node.status === 'error' && 'border-red-500',
        node.status === 'pending' && 'border-slate-200 dark:border-slate-600'
      )}>
        <span className={className}>{icon}</span>
      </div>
      
      {/* Content */}
      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <p className={cn(
            'text-sm font-medium truncate',
            node.status === 'pending' && 'text-slate-400 dark:text-slate-500',
            node.status === 'running' && 'text-blue-500',
            node.status === 'complete' && 'text-slate-900 dark:text-slate-100',
            node.status === 'skipped' && 'text-slate-400 dark:text-slate-500 line-through',
            node.status === 'error' && 'text-red-500'
          )}>
            {NODE_LABELS[node.name] ?? node.name}
          </p>
          {duration && node.status !== 'skipped' && (
            <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">
              {duration}s
            </span>
          )}
          {node.status === 'skipped' && (
            <span className="text-xs text-slate-400 dark:text-slate-500 italic shrink-0">
              skipped
            </span>
          )}
        </div>
        
        {node.message && node.status !== 'pending' && node.status !== 'skipped' && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
            {node.message}
          </p>
        )}
        
        {/* Data preview for tool results */}
        {node.data && node.status === 'complete' && (
          <div className="mt-1 p-2 bg-slate-100 dark:bg-slate-700 rounded text-xs font-mono overflow-hidden">
            <pre className="whitespace-pre-wrap break-words max-h-20 overflow-y-auto text-slate-700 dark:text-slate-300">
              {JSON.stringify(node.data, null, 2).slice(0, 200)}
              {JSON.stringify(node.data).length > 200 && '...'}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

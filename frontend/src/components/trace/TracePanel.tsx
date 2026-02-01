import { useChatStore } from '../../stores/chatStore';
import { TraceNode } from './TraceNode';
import { Activity, ChevronRight, X } from 'lucide-react';
import { cn } from '../../lib/utils';

interface TracePanelProps {
  embedded?: boolean; // When true, hides toggle button and header close
}

export function TracePanel({ embedded = false }: TracePanelProps) {
  const traceNodes = useChatStore((state) => state.traceNodes);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const isOpen = useChatStore((state) => state.isTracePanelOpen);
  const togglePanel = useChatStore((state) => state.toggleTracePanel);
  
  // Calculate timing
  const startTime = traceNodes.find((n) => n.startTime)?.startTime;
  const endTime = [...traceNodes].reverse().find((n) => n.endTime)?.endTime;
  const totalDuration = startTime && endTime
    ? ((endTime - startTime) / 1000).toFixed(2)
    : null;
  
  const completedCount = traceNodes.filter((n) => n.status === 'complete' || n.status === 'skipped').length;
  const skippedCount = traceNodes.filter((n) => n.status === 'skipped').length;
  const totalCount = traceNodes.length;
  
  // In embedded mode, always show the panel content without toggle
  if (!embedded && !isOpen) {
    return (
      <button
        onClick={togglePanel}
        className={cn(
          'fixed right-4 top-1/2 -translate-y-1/2 z-50',
          'p-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg',
          'hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors',
          isStreaming && 'animate-pulse border-blue-500'
        )}
        title="Show trace panel"
      >
        <ChevronRight className="w-5 h-5" />
      </button>
    );
  }
  
  return (
    <div className={cn(
      "bg-white dark:bg-slate-900 flex flex-col h-full",
      !embedded && "w-80 border-l border-slate-200 dark:border-slate-700"
    )}>
      {/* Header - hide in embedded mode (parent provides header) */}
      {!embedded && (
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Activity className={cn(
              'w-4 h-4',
              isStreaming && 'text-blue-500 animate-pulse'
            )} />
            <h2 className="font-semibold text-sm">Workflow Trace</h2>
          </div>
          <button
            onClick={togglePanel}
            className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      
      {/* Progress summary */}
      {traceNodes.length > 0 && (
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-500 dark:text-slate-400">
              {completedCount}/{totalCount} done
              {skippedCount > 0 && <span className="text-slate-400"> ({skippedCount} skipped)</span>}
            </span>
            {totalDuration && (
              <span className="text-slate-500 dark:text-slate-400">
                {totalDuration}s
              </span>
            )}
          </div>
          <div className="mt-2 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className={cn(
                'h-full transition-all duration-300',
                isStreaming ? 'bg-blue-500' : 'bg-green-500'
              )}
              style={{ width: `${totalCount > 0 ? (completedCount / totalCount) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}
      
      {/* Trace nodes */}
      <div className="flex-1 overflow-y-auto p-4">
        {traceNodes.length === 0 ? (
          <div className="text-center text-slate-500 dark:text-slate-400 text-sm py-8">
            <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No workflow trace yet</p>
            <p className="text-xs mt-1">Send a message to see the agent's thought process</p>
          </div>
        ) : (
          <div className="space-y-0">
            {traceNodes.map((node, index) => (
              <TraceNode
                key={node.name}
                node={node}
                isLast={index === traceNodes.length - 1}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

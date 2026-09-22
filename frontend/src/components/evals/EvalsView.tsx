import { useEffect } from 'react';
import { ListChecks, Loader2, MessageSquare } from 'lucide-react';
import { useEvalStore } from '../../stores/evalStore';
import { CaseDetail } from './CaseDetail';
import { EvalRunView } from './EvalRunView';
import { TraceViewer } from './TraceViewer';

export function EvalsView() {
  const { mode, loadIndex, selectedRunId, selectedCaseId, selectCase, selectedConversationId, conversationTraces } = useEvalStore();

  useEffect(() => {
    loadIndex();
  }, [loadIndex]);

  if (mode === 'conversations') {
    if (selectedConversationId && conversationTraces.length === 0) {
      return <div className="flex-1 flex items-center justify-center"><Loader2 className="animate-spin text-slate-400" /></div>;
    }
    if (!selectedConversationId) {
      return <Empty icon={<MessageSquare size={44} />} text="Pick a conversation to see each turn as a predicate tree over the agent's state machine." />;
    }
    return (
      <div className="flex-1 min-h-0 flex flex-col">
        <TraceViewer
          key={`${selectedConversationId}:${conversationTraces.length}`}
          turns={conversationTraces.map((t) => ({ user: t.user, response: t.response, trace: t.trace }))}
        />
      </div>
    );
  }

  if (selectedCaseId) return <CaseDetail onBack={() => selectCase(null)} />;
  if (!selectedRunId) {
    return <Empty icon={<ListChecks size={44} />} text="Start a suite or pick a past run to see scores, latency, cost and failure analysis." />;
  }
  return <EvalRunView onOpenCase={(id) => selectCase(id)} />;
}

function Empty({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex-1 flex items-center justify-center text-slate-500 dark:text-slate-400 p-6">
      <div className="text-center max-w-sm">
        <div className="mx-auto mb-3 opacity-50 w-fit">{icon}</div>
        <p className="text-sm">{text}</p>
      </div>
    </div>
  );
}

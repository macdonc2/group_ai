import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Crosshair, Send, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../../lib/api';

export interface GraphAskStep {
  tool: string;
  args: Record<string, unknown>;
  summary: string;
  duration_ms: number;
}

export interface GraphAskResponse {
  answer: string;
  highlight_node_ids: string[];
  filter: { node_types: string[]; edge_types: string[] } | null;
  steps: GraphAskStep[];
  stopped: 'answered' | 'step_limit' | 'timeout' | 'error';
  usage: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    duration_ms: number;
    cost_usd: number | null;
  };
}

interface Turn {
  question: string;
  response?: GraphAskResponse;
  error?: string;
}

interface GraphAskPanelProps {
  selectedNodeId: string | null;
  selectedLabel: string | null;
  /** Apply an answer to the graph view (highlight nodes, optionally filter types). */
  onApply: (response: GraphAskResponse, reveal?: boolean) => void;
  /** Question queued from elsewhere in the explorer ("Ask about this node"). */
  pending: string | null;
  onPendingConsumed: () => void;
}

const SUGGESTIONS = [
  'Who do I know, and how?',
  'Which places do the people I know go to?',
  'What topics come up most?',
  'Show only people and pets',
];

function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(',') : String(v)}`)
    .join(' ');
}

function Steps({ response }: { response: GraphAskResponse }) {
  const [open, setOpen] = useState(false);
  const { steps, usage } = response;
  const seconds = (usage.duration_ms / 1000).toFixed(1);
  const cost = usage.cost_usd != null ? ` · $${usage.cost_usd.toFixed(4)}` : '';
  return (
    <div className="mt-2 text-xs text-gray-400">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 hover:text-gray-200"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {steps.length === 0 ? 'Answered from the summary' : `${steps.length} lookup${steps.length === 1 ? '' : 's'}`}
        {` · ${seconds}s${cost}`}
      </button>
      {open && steps.length > 0 && (
        <ol className="mt-1.5 space-y-1.5 border-l border-gray-700 pl-3">
          {steps.map((step, i) => (
            <li key={i}>
              <div className="font-mono text-gray-300 break-words">
                {step.tool}
                <span className="text-gray-500"> {formatArgs(step.args)}</span>
              </div>
              <div className="text-gray-500 break-words">{step.summary}</div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function GraphAskPanel({ selectedNodeId, selectedLabel, onApply, pending, onPendingConsumed }: GraphAskPanelProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const turnsRef = useRef<Turn[]>([]);
  turnsRef.current = turns;

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [turns, busy]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const history = turnsRef.current
      .filter((t) => t.response)
      .slice(-3)
      .map((t) => ({ question: t.question, answer: t.response!.answer.slice(0, 2000) }));
    setInput('');
    setBusy(true);
    setTurns((prev) => [...prev, { question: q }]);
    try {
      const response = await api.askKnowledgeGraph(q, selectedNodeId, history);
      setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, response } : t)));
      onApply(response);
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Request failed';
      setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, error } : t)));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (pending && !busy) {
      onPendingConsumed();
      void ask(pending);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, busy]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-4">
        {turns.length === 0 && (
          <div className="text-sm text-gray-400">
            <p className="flex items-center gap-1.5 text-gray-200 font-medium mb-1">
              <Sparkles size={14} /> Ask about your graph
            </p>
            <p className="mb-3">
              Answers come from what is stored in the graph. Matching nodes are highlighted, and you can ask it to
              filter the view.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void ask(s)}
                  className="px-2.5 py-1.5 rounded-full bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs text-left"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className="space-y-2">
            <div className="ml-6 rounded-lg bg-blue-600/90 text-white text-sm px-3 py-2 break-words">
              {turn.question}
            </div>
            {turn.response && (
              <div className="mr-2 rounded-lg bg-gray-800 px-3 py-2">
                {turn.response.stopped !== 'answered' && (
                  <p className="text-xs text-amber-400 mb-1">
                    {turn.response.stopped === 'step_limit'
                      ? 'Stopped at the step limit'
                      : turn.response.stopped === 'timeout'
                        ? 'Timed out'
                        : 'Something went wrong'}
                  </p>
                )}
                <div className="text-sm text-gray-200 break-words space-y-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:text-white [&_a]:text-blue-400 [&_code]:text-amber-300">
                  {/* Stored graph text is untrusted: no images, links open in a new tab. */}
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    disallowedElements={['img']}
                    components={{
                      a: ({ children, href }) => (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {turn.response.answer}
                  </ReactMarkdown>
                </div>
                {(turn.response.highlight_node_ids.length > 0 || turn.response.filter) && (
                  <button
                    onClick={() => onApply(turn.response!, true)}
                    className="mt-2 flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                    title="Show this answer in the graph"
                  >
                    <Crosshair size={12} />
                    {turn.response.filter
                      ? 'Apply filter'
                      : `Show ${turn.response.highlight_node_ids.length} node${turn.response.highlight_node_ids.length === 1 ? '' : 's'} in graph`}
                  </button>
                )}
                <Steps response={turn.response} />
              </div>
            )}
            {turn.error && (
              <div className="mr-2 rounded-lg bg-red-950/60 text-red-300 text-sm px-3 py-2 break-words">
                {turn.error}
              </div>
            )}
            {!turn.response && !turn.error && (
              <div className="mr-2 rounded-lg bg-gray-800 px-3 py-2 text-sm text-gray-400 animate-pulse">
                Looking through the graph…
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
        }}
        className="shrink-0 border-t border-gray-700 p-2"
      >
        {selectedLabel && (
          <p className="text-xs text-gray-500 mb-1 truncate">
            Selected: <span className="text-gray-300">{selectedLabel}</span> (say “this” to refer to it)
          </p>
        )}
        <div className="flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your graph…"
            maxLength={2000}
            className="flex-1 min-w-0 rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-base sm:text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="p-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 touch-manipulation"
            title="Ask"
          >
            <Send size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}

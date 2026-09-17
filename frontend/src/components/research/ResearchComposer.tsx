import { useEffect, useRef, useState } from 'react';
import { FlaskConical, GraduationCap, Wrench, BarChart3, ArrowRight, Gauge } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/themeStore';
import { getWrestler } from '../../lib/wrestlers';

interface ResearchComposerProps {
  onStart: (question: string, depth: 1 | 2 | 3) => void;
  error: string | null;
}

const DEPTHS: { value: 1 | 2 | 3; label: string; blurb: string; time: string }[] = [
  { value: 1, label: 'Quick', blurb: 'One pass per lane', time: '~5 min' },
  { value: 2, label: 'Standard', blurb: 'Summarise, find gaps, search again', time: '~9 min' },
  { value: 3, label: 'Deep', blurb: 'Two rounds of gap-driven follow-up', time: '~13 min' },
];

const EXAMPLES = [
  'How do transformer-based and physics-informed neural networks compare for seismic full-waveform inversion?',
  'What are the practical trade-offs between vector databases for production RAG at 10M+ documents?',
  'Does speculative decoding deliver the reported speedups on consumer GPUs?',
];

export function ResearchComposer({ onStart, error }: ResearchComposerProps) {
  const [question, setQuestion] = useState('');
  const [depth, setDepth] = useState<1 | 2 | 3>(1);
  const ref = useRef<HTMLTextAreaElement>(null);
  const wrestler = getWrestler(useThemeStore((s) => s.wrestler));

  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
    }
  }, [question]);

  const submit = () => {
    const q = question.trim();
    if (q.length >= 8) onStart(q, depth);
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-8 sm:py-14">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 mb-3">
            <FlaskConical className="w-6 h-6" />
          </div>
          <h2 className="text-xl sm:text-2xl font-semibold wt-display">Deep Research</h2>
          {wrestler && (
            <p className="text-xs mt-1 wt-accent-text font-medium">Overview and narration voiced by {wrestler.name}</p>
          )}
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-xl mx-auto">
            Ask a question. Three agents research it in parallel, the results are reconciled
            into one overview with figures, and you can read it or listen to it.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6 text-xs">
          <Lane icon={<GraduationCap className="w-4 h-4" />} title="Academic" text="arXiv and Semantic Scholar: what the literature has shown." />
          <Lane icon={<Wrench className="w-4 h-4" />} title="Practical" text="Web, docs and GitHub: how it is built and what breaks." />
          <Lane icon={<BarChart3 className="w-4 h-4" />} title="Empirical" text="Reported numbers, benchmarks and comparisons, charted." />
        </div>

        <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-2">
          <textarea
            ref={ref}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
            }}
            placeholder="What do you want researched?"
            rows={3}
            className={cn(
              'w-full bg-transparent resize-none border-0 focus:outline-none focus:ring-0',
              'text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500',
              'px-3 py-2 min-h-[88px] max-h-[240px]'
            )}
            style={{ fontSize: '16px' }}
          />
          <div className="flex items-center justify-between px-2 pb-1 gap-2 flex-wrap">
            <div className="flex items-center gap-1" role="radiogroup" aria-label="Research depth">
              <Gauge className="w-4 h-4 text-slate-400 mr-1" />
              {DEPTHS.map((d) => (
                <button
                  key={d.value}
                  role="radio"
                  aria-checked={depth === d.value}
                  onClick={() => setDepth(d.value)}
                  title={`${d.blurb} · ${d.time}`}
                  className={cn(
                    'px-2.5 py-1 text-xs rounded-md border transition-colors',
                    depth === d.value
                      ? 'bg-blue-600 border-blue-600 text-white'
                      : 'border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                  )}
                >
                  {d.label}
                </button>
              ))}
              <span className="hidden sm:inline text-xs text-slate-400 dark:text-slate-500 ml-2">{DEPTHS.find((d) => d.value === depth)?.blurb} · {DEPTHS.find((d) => d.value === depth)?.time}</span>
            </div>
            <button
              onClick={submit}
              disabled={question.trim().length < 8}
              className="ml-auto inline-flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors touch-manipulation"
            >
              Run research <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <div className="mt-8">
          <p className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 mb-2">Try one</p>
          <div className="flex flex-col gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setQuestion(ex)}
                className="text-left text-sm px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Lane({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
      <div className="flex items-center gap-2 font-medium text-slate-700 dark:text-slate-200 mb-1">{icon}{title}</div>
      <p className="text-slate-500 dark:text-slate-400 leading-relaxed">{text}</p>
    </div>
  );
}

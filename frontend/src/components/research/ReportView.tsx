import { useMemo } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../../lib/api';
import type { ResearchFigure, ResearchSource } from '../../types';

interface ReportViewProps {
  jobId: string;
  markdown: string;
  figures: ResearchFigure[];
  sources: ResearchSource[];
  streaming?: boolean;
}

const FIGURE_SRC = /^figure:(\d+)$/;

/** Turn `[3]` citations into links to the reference list. */
function linkCitations(md: string): string {
  return md.replace(/\[(\d+)\](?!\()/g, (_m, n: string) => `[[${n}]](#ref-${n})`);
}

export function ReportView({ jobId, markdown, figures, sources, streaming = false }: ReportViewProps) {
  const figMap = useMemo(() => new Map(figures.map((f) => [f.ordinal, f])), [figures]);
  const body = useMemo(() => linkCitations(markdown), [markdown]);
  const refs = useMemo(() => new Set(sources.map((s) => s.ref)), [sources]);

  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 py-6 text-slate-800 dark:text-slate-100 leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (FIGURE_SRC.test(url) ? url : defaultUrlTransform(url))}
        components={{
          h1: ({ children }) => <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-4 mt-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg sm:text-xl font-semibold mt-8 mb-3 pb-1 border-b border-slate-200 dark:border-slate-700">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold mt-5 mb-2">{children}</h3>,
          p: ({ children }) => <p className="my-3 text-[15px] sm:text-base">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-6 my-3 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-6 my-3 space-y-2 text-sm">{children}</ol>,
          li: ({ children, ...rest }) => {
            // Reference list items get anchors so citations can jump to them.
            const text = Array.isArray(children) ? children : [children];
            const first = typeof text[0] === 'string' ? text[0] : '';
            const m = /^(\d+)\.\s/.exec(first);
            const node = rest.node as { position?: { start: { line: number } } } | undefined;
            void node;
            return <li className="break-words" id={m && refs.has(Number(m[1])) ? `ref-${m[1]}` : undefined}>{children}</li>;
          },
          blockquote: ({ children }) => <blockquote className="border-l-4 border-blue-300 dark:border-blue-700 pl-4 my-3 text-slate-600 dark:text-slate-300 italic">{children}</blockquote>,
          code: ({ children, className }) => {
            const block = Boolean(className);
            return block
              ? <code className="block bg-slate-100 dark:bg-slate-800 rounded-md p-3 text-xs overflow-x-auto my-3 font-mono">{children}</code>
              : <code className="bg-slate-100 dark:bg-slate-800 rounded px-1 py-0.5 text-[0.9em] font-mono">{children}</code>;
          },
          pre: ({ children }) => <>{children}</>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          a: ({ href, children }) => {
            const isCite = href?.startsWith('#ref-');
            return isCite
              ? <a href={href} className="text-blue-600 dark:text-blue-400 no-underline text-[0.8em] align-super">{children}</a>
              : <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 dark:text-blue-400 underline decoration-blue-300 dark:decoration-blue-700 underline-offset-2 break-all">{children}</a>;
          },
          hr: () => <hr className="my-6 border-slate-200 dark:border-slate-700" />,
          img: ({ src, alt }) => {
            const m = FIGURE_SRC.exec(String(src ?? ''));
            if (!m) return <img src={src} alt={alt} className="max-w-full rounded-lg my-4" />;
            const n = Number(m[1]);
            const fig = figMap.get(n);
            const rawCaption = fig?.caption ?? alt ?? `Figure ${n}`;
            // Captions for lifted figures end with " — [Paper title](url)"; render that as the link.
            const caption = rawCaption.replace(/\s+—\s+\[[^\]]+\]\([^)]+\)\s*$/, '');
            const fromPaper = fig?.origin === 'source';
            return (
              <figure className="my-6">
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white p-2 overflow-hidden">
                  <img
                    src={api.researchFigureUrl(jobId, n)}
                    alt={caption}
                    loading="lazy"
                    className="w-full h-auto"
                  />
                </div>
                <figcaption className="text-sm text-slate-500 dark:text-slate-400 italic mt-2 text-center">
                  {caption}
                  {fromPaper && fig?.source_url && (
                    <>
                      {' '}
                      <a href={fig.source_url} target="_blank" rel="noreferrer" className="not-italic text-blue-600 dark:text-blue-400 underline underline-offset-2">
                        {fig.source_title ? `Source: ${fig.source_title}` : 'View paper'}
                      </a>
                    </>
                  )}
                  {!fromPaper && <span className="not-italic text-[11px] ml-1 text-slate-400">(chart from extracted data)</span>}
                </figcaption>
              </figure>
            );
          },
        }}
      >
        {body}
      </ReactMarkdown>
      {streaming && <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse align-middle ml-1" aria-hidden />}
    </article>
  );
}

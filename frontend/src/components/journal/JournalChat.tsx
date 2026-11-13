import { useEffect, useRef, useState } from 'react';
import { Loader2, Send, Sparkles, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '../../lib/utils';
import { useJournalStore } from '../../stores/journalStore';

const STARTERS = [
  'Give me a few prompts for today',
  "What's on my calendar today?",
  'What did I write about this past week?',
];

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: string }) {
  return (
    <div className={cn('flex', role === 'user' ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[88%] rounded-lg px-3 py-2 text-sm',
          role === 'user'
            ? 'bg-blue-600 text-white wt-bubble-user'
            : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 wt-bubble-bot',
        )}
      >
        <div className="prose prose-sm dark:prose-invert max-w-none break-words [&>*:last-child]:mb-0 [&>*:first-child]:mt-0">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

/** The side conversation about the open day. Replies are never part of the journal itself. */
export function JournalChat() {
  const messages = useJournalStore((s) => s.messages);
  const sending = useJournalStore((s) => s.sending);
  const streaming = useJournalStore((s) => s.streaming);
  const activity = useJournalStore((s) => s.activity);
  const sendMessage = useJournalStore((s) => s.sendMessage);
  const clearChat = useJournalStore((s) => s.clearChat);
  const [text, setText] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, streaming, activity]);

  const send = (value: string) => {
    if (!value.trim() || sending) return;
    setText('');
    sendMessage(value);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
        <Sparkles className="w-4 h-4 text-blue-500" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">Talk it over</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate">Knows this day, your memory and your calendar</p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            disabled={sending}
            className="p-1.5 rounded text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-colors"
            title="Clear this day's conversation"
            aria-label="Clear this day's conversation"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {messages.length === 0 && !sending && (
          <div className="pt-4 space-y-2">
            <p className="text-sm text-slate-500 dark:text-slate-400 px-1">
              Ask for a writing prompt, look back at earlier entries, or have something added to your calendar.
            </p>
            {STARTERS.map((starter) => (
              <button
                key={starter}
                onClick={() => send(starter)}
                className="block w-full text-left text-sm px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                {starter}
              </button>
            ))}
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} role={m.role}>{m.content}</Bubble>
        ))}
        {sending && streaming && <Bubble role="assistant">{streaming}</Bubble>}
        {sending && !streaming && (
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 px-1 py-1">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {activity ?? 'Thinking'}…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); send(text); }}
        className="p-3 border-t border-slate-200 dark:border-slate-700 flex items-end gap-2 shrink-0 safe-area-inset-bottom"
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(text);
            }
          }}
          rows={1}
          maxLength={4000}
          placeholder="Ask about this day…"
          aria-label="Message the journal assistant"
          className="flex-1 resize-none rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm max-h-32 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={!text.trim() || sending}
          className="p-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors wt-accent-bg"
          aria-label="Send"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}

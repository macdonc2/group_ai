import { cn } from '../../lib/utils';
import type { Message } from '../../types';
import { User, Bot } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';
import { getWrestler } from '../../lib/wrestlers';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const wrestler = getWrestler(useThemeStore((s) => s.wrestler));
  
  return (
    <div
      className={cn(
        'flex gap-2 sm:gap-3 p-2 sm:p-4',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {/* Avatar - smaller on mobile */}
      <div
        className={cn(
          'shrink-0 w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center overflow-hidden',
          isUser
            ? 'bg-blue-600 text-white wt-accent-bg'
            : wrestler ? 'wt-ring' : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200'
        )}
      >
        {isUser
          ? <User className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          : wrestler
            ? <img src={wrestler.icon} alt={wrestler.shortName} className="w-full h-full object-cover" />
            : <Bot className="w-3.5 h-3.5 sm:w-4 sm:h-4" />}
      </div>
      
      {/* Message content */}
      <div
        className={cn(
          'flex-1 max-w-[85%] sm:max-w-[80%] rounded-lg px-3 sm:px-4 py-2',
          isUser
            ? 'bg-blue-600 text-white ml-auto wt-bubble-user'
            : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 wt-bubble-bot'
        )}
      >
        <div className="prose prose-sm dark:prose-invert max-w-none break-words">
          <ReactMarkdown 
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({ children }) => (
                <table className="min-w-full border-collapse border border-slate-300 dark:border-slate-600 my-2">
                  {children}
                </table>
              ),
              thead: ({ children }) => (
                <thead className="bg-slate-200 dark:bg-slate-700">
                  {children}
                </thead>
              ),
              th: ({ children }) => (
                <th className="border border-slate-300 dark:border-slate-600 px-3 py-1 text-left font-semibold">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-slate-300 dark:border-slate-600 px-3 py-1">
                  {children}
                </td>
              ),
              p: ({ children }) => (
                <p className="mb-2 last:mb-0">{children}</p>
              ),
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>
        
        {/* Tool calls if any */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-2 pt-2 border-t border-slate-300/50 dark:border-slate-600/50">
            <div className="text-xs opacity-70">
              Tools used: {message.toolCalls.map((t) => t.name).join(', ')}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

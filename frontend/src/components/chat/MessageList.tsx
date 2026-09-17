import { useEffect, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import { useChatStore } from '../../stores/chatStore';
import { Loader2 } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';
import { getWrestler } from '../../lib/wrestlers';
import { useContentWidth } from '../../lib/layout';

export function MessageList() {
  const messages = useChatStore((state) => state.messages);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const wrestler = getWrestler(useThemeStore((s) => s.wrestler));
  const width = useContentWidth('chat');
  const scrollRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);
  
  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 dark:text-slate-400">
        <div className="text-center px-6">
          {wrestler && (
            <img src={wrestler.icon} alt={wrestler.name} className="w-24 h-24 rounded-full object-cover mx-auto mb-4 wt-ring wt-glow-shadow" />
          )}
          <p className="text-lg font-medium">{wrestler ? wrestler.welcome : 'Welcome to Agent Chat'}</p>
          <p className="text-sm mt-1">{wrestler ? wrestler.tagline : 'Start a conversation to begin'}</p>
        </div>
      </div>
    );
  }
  
  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto"
    >
      <div className={`${width} mx-auto py-4`}>
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        
        {/* Streaming indicator */}
        {isStreaming && (
          <div className="flex gap-3 p-4">
            <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 overflow-hidden">
              {wrestler ? <img src={wrestler.icon} alt="" className="w-full h-full object-cover animate-pulse" /> : <Loader2 className="w-4 h-4 animate-spin" />}
            </div>
            <div className="flex-1 max-w-[80%] rounded-lg px-4 py-2 bg-slate-100 dark:bg-slate-800">
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <span>{wrestler ? wrestler.thinking : 'Thinking'}</span>
                <span className="animate-pulse">...</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

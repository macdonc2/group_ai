import { useState, useRef, useEffect } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useThemeStore, type ChatEngine } from '../../stores/themeStore';
import { useAuthStore } from '../../stores/authStore';
import { getWrestler } from '../../lib/wrestlers';
import { useContentWidth } from '../../lib/layout';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Show the FSM/Loop engine switch (1:1 chat only; rendered for superusers). */
  showEngineToggle?: boolean;
}

const ENGINES: { key: ChatEngine; label: string; hint: string }[] = [
  { key: 'fsm', label: 'FSM', hint: 'Node workflow: one router call, one tool, then the reply' },
  { key: 'loop', label: 'Loop', hint: 'Single tool loop: the model calls tools itself, several per turn' },
];

export function ChatInput({ onSend, disabled, placeholder = 'Type a message...', showEngineToggle }: ChatInputProps) {
  const chatEngine = useThemeStore((s) => s.chatEngine);
  const setChatEngine = useThemeStore((s) => s.setChatEngine);
  const canPickEngine = useAuthStore((s) => Boolean(s.user?.is_superuser)) && Boolean(showEngineToggle);
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wrestler = getWrestler(useThemeStore((s) => s.wrestler));
  const width = useContentWidth('chat');
  
  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [input]);
  
  const handleSubmit = () => {
    const trimmed = input.trim();
    if (trimmed && !disabled) {
      onSend(trimmed);
      setInput('');
    }
  };
  
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };
  
  return (
    <div className="border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 sm:p-4 safe-area-inset-bottom">
      <div className={`${width} mx-auto`}>
        <div className="flex items-end gap-2 bg-slate-100 dark:bg-slate-800 rounded-lg p-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={wrestler ? wrestler.prompt : placeholder}
            disabled={disabled}
            rows={1}
            className={cn(
              'flex-1 bg-transparent resize-none border-0 focus:outline-none focus:ring-0',
              'text-base sm:text-sm placeholder:text-slate-400 dark:placeholder:text-slate-500',
              'text-slate-900 dark:text-slate-100',
              'min-h-[44px] sm:min-h-[40px] max-h-[200px] py-2.5 sm:py-2 px-2'
            )}
            style={{ fontSize: '16px' }} // Prevent iOS zoom on focus
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !input.trim()}
            className={cn(
              'shrink-0 p-2.5 sm:p-2 rounded-md transition-colors touch-manipulation',
              'bg-blue-600 text-white wt-accent-bg',
              'hover:bg-blue-700 active:bg-blue-800',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {disabled ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
        <div className="mt-2 flex items-center justify-center gap-3">
          {canPickEngine && (
            <div
              role="radiogroup"
              aria-label="Chat engine"
              className="inline-flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden text-xs"
            >
              {ENGINES.map((e) => (
                <button
                  key={e.key}
                  type="button"
                  role="radio"
                  aria-checked={chatEngine === e.key}
                  title={e.hint}
                  disabled={disabled}
                  onClick={() => setChatEngine(e.key)}
                  className={cn(
                    'px-2.5 py-1 transition-colors touch-manipulation disabled:cursor-not-allowed',
                    chatEngine === e.key
                      ? 'bg-blue-600 text-white wt-accent-bg'
                      : 'bg-white dark:bg-slate-900 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                  )}
                >
                  {e.label}
                </button>
              ))}
            </div>
          )}
          <p className="hidden sm:block text-xs text-slate-400 dark:text-slate-500 text-center">
            Press Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}

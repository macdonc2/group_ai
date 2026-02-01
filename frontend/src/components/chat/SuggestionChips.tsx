import { useChatStore } from '../../stores/chatStore';
import { Lightbulb, Search, Sparkles } from 'lucide-react';
import { cn } from '../../lib/utils';

interface SuggestionChipsProps {
  onSelect: (suggestion: string) => void;
}

const ICON_MAP: Record<string, React.ReactNode> = {
  web_search: <Search className="w-3 h-3" />,
  random_fact: <Sparkles className="w-3 h-3" />,
  follow_up: <Lightbulb className="w-3 h-3" />,
};

export function SuggestionChips({ onSelect }: SuggestionChipsProps) {
  const suggestions = useChatStore((state) => state.suggestions);
  
  if (suggestions.length === 0) return null;
  
  return (
    <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-4 py-3">
      <div className="max-w-3xl mx-auto">
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">Suggestions</p>
        <div className="flex flex-wrap gap-2">
          {suggestions.map((suggestion, index) => (
            <button
              key={index}
              onClick={() => onSelect(suggestion.description)}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                'text-xs font-medium',
                'bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600',
                'text-slate-700 dark:text-slate-200',
                'hover:bg-slate-100 dark:hover:bg-slate-600',
                'transition-colors'
              )}
            >
              {ICON_MAP[suggestion.action_type ?? 'follow_up'] ?? <Lightbulb className="w-3 h-3" />}
              {suggestion.title}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

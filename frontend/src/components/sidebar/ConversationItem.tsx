import { cn, formatTimestamp, truncate } from '../../lib/utils';
import type { ConversationListItem } from '../../types';
import { MessageSquare, Trash2 } from 'lucide-react';

interface ConversationItemProps {
  conversation: ConversationListItem;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

export function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: ConversationItemProps) {
  const title = conversation.title || `Conversation ${conversation.id.slice(0, 8)}`;
  const updatedAt = new Date(conversation.updated_at);
  
  return (
    <div
      className={cn(
        'group flex items-center gap-2 p-3 rounded-lg cursor-pointer transition-colors',
        isActive
          ? 'bg-blue-600 text-white'
          : 'hover:bg-slate-100 dark:hover:bg-slate-800'
      )}
      onClick={onSelect}
    >
      <MessageSquare className="w-4 h-4 shrink-0" />
      
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">
          {truncate(title, 25)}
        </p>
        <div className={cn(
          'flex items-center gap-2 text-xs',
          isActive ? 'opacity-80' : 'text-slate-500 dark:text-slate-400'
        )}>
          <span>{conversation.message_count} messages</span>
          <span>•</span>
          <span>{formatTimestamp(updatedAt)}</span>
        </div>
      </div>
      
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className={cn(
          'p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity',
          isActive
            ? 'hover:bg-white/20'
            : 'hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-500'
        )}
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

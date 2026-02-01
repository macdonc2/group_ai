import { useEffect } from 'react';
import { useChatStore } from '../../stores/chatStore';
import { ConversationItem } from './ConversationItem';
import { api } from '../../lib/api';
import { Plus, MessageSquare, ChevronLeft } from 'lucide-react';
import { cn } from '../../lib/utils';

interface ConversationListProps {
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  hideWrapper?: boolean;
}

export function ConversationList({
  onNewConversation,
  onSelectConversation,
  hideWrapper = false,
}: ConversationListProps) {
  const conversations = useChatStore((state) => state.conversations);
  const setConversations = useChatStore((state) => state.setConversations);
  const removeConversation = useChatStore((state) => state.removeConversation);
  const currentConversationId = useChatStore((state) => state.conversationId);
  const isSidebarOpen = useChatStore((state) => state.isSidebarOpen);
  const toggleSidebar = useChatStore((state) => state.toggleSidebar);
  
  // Fetch conversations on mount
  useEffect(() => {
    const fetchConversations = async () => {
      try {
        const data = await api.listConversations();
        setConversations(data);
      } catch (error) {
        console.error('Failed to fetch conversations:', error);
      }
    };
    fetchConversations();
  }, [setConversations]);
  
  const handleDelete = async (id: string) => {
    // Confirm before deleting
    const confirmed = window.confirm('Delete this conversation? This cannot be undone.');
    if (!confirmed) return;
    
    try {
      await api.deleteConversation(id);
      removeConversation(id);
      
      // If we deleted the current conversation, clear the view
      if (id === currentConversationId) {
        onNewConversation();
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };
  
  if (!isSidebarOpen) {
    return (
      <button
        onClick={toggleSidebar}
        className={cn(
          'fixed left-4 top-1/2 -translate-y-1/2 z-50',
          'p-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg',
          'hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors'
        )}
        title="Show conversations"
      >
        <MessageSquare className="w-5 h-5" />
      </button>
    );
  }
  
  const content = (
    <>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
        <h2 className="font-semibold text-sm">Conversations</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={onNewConversation}
            className="p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded transition-colors"
            title="New conversation"
          >
            <Plus className="w-4 h-4" />
          </button>
          {!hideWrapper && (
            <button
              onClick={toggleSidebar}
              className="p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded transition-colors"
              title="Hide sidebar"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      
      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto p-2">
        {conversations.length === 0 ? (
          <div className="text-center text-slate-500 dark:text-slate-400 text-sm py-8">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No conversations yet</p>
            <button
              onClick={onNewConversation}
              className="mt-2 text-blue-500 hover:underline text-xs"
            >
              Start a new conversation
            </button>
          </div>
        ) : (
          <div className="space-y-1">
            {conversations.map((conv) => (
              <ConversationItem
                key={conv.id}
                conversation={conv}
                isActive={conv.id === currentConversationId}
                onSelect={() => onSelectConversation(conv.id)}
                onDelete={() => handleDelete(conv.id)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );

  if (hideWrapper) {
    return <div className="flex flex-col h-full">{content}</div>;
  }

  return (
    <div className="w-72 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 flex flex-col h-full">
      {content}
    </div>
  );
}

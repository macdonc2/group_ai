import { useState, useRef, useEffect } from 'react';
import { Send, Users, Calendar, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { GroupMessage, GroupDetail, ExtractedEvent, SocialSuggestion } from '../../types';
import { api } from '../../lib/api';
import { useGroupStore } from '../../stores/groupStore';

interface AgentStatus {
  isThinking: boolean;
  message: string | null;
}

interface StreamingMessage {
  id: string;
  content: string;
  isComplete: boolean;
}

interface GroupChatProps {
  group: GroupDetail;
  messages: GroupMessage[];
  typingUsers: string[];
  onlineUsers: string[];
  onSendMessage: (content: string) => void;
  onTyping: (isTyping: boolean) => void;
  events: ExtractedEvent[];
  suggestions: SocialSuggestion[];
  currentUserId: string;
  isConnected: boolean;
  connectionError?: string | null;
  agentStatus: AgentStatus;
  streamingMessage?: StreamingMessage | null;
}

export function GroupChat({
  group,
  messages,
  typingUsers,
  onlineUsers,
  onSendMessage,
  onTyping,
  events,
  suggestions,
  currentUserId,
  isConnected,
  connectionError,
  agentStatus,
  streamingMessage,
}: GroupChatProps) {
  const [input, setInput] = useState('');
  const [showEvents, setShowEvents] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage?.content]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    
    // Handle typing indicator
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
    onTyping(true);
    typingTimeoutRef.current = setTimeout(() => {
      onTyping(false);
    }, 2000);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    onSendMessage(input.trim());
    setInput('');
    onTyping(false);
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const getMemberEmail = (userId: string) => {
    const member = group.members.find(m => m.user_id === userId);
    return member?.user_email || userId.slice(0, 8);
  };

  const upcomingEvents = events.filter(e => {
    if (!e.event_datetime) return true;
    // Ensure UTC parsing by appending 'Z' if no timezone indicator present
    const dtString = e.event_datetime;
    const hasTimezone = dtString.includes('Z') || dtString.includes('+') || dtString.includes('-', 10);
    const utcString = hasTimezone ? dtString : dtString + 'Z';
    return new Date(utcString) > new Date();
  }).slice(0, 5);

  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center">
            <Users className="text-white" size={18} />
          </div>
          <div className="ml-3">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {group.name}
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center">
              <span className={`w-2 h-2 rounded-full mr-1.5 ${isConnected ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'}`} />
              {isConnected ? `${onlineUsers.length} online` : 'Connecting...'} • {group.member_count} members
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setShowEvents(!showEvents)}
            className={`p-2 rounded-lg transition-colors ${
              showEvents 
                ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
            title="Events & Suggestions"
          >
            <Calendar size={20} />
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-2 sm:p-4 space-y-3 sm:space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center text-gray-500 dark:text-gray-400">
              <Users size={48} className="mb-4 opacity-50" />
              <p>No messages yet</p>
              <p className="text-sm">Start the conversation!</p>
              <p className="text-xs mt-2 text-purple-500 dark:text-purple-400">
                <Sparkles size={12} className="inline mr-1" />
                Tip: Type <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">@agent</code> to ask the AI assistant
              </p>
            </div>
          ) : (
            messages.map((message) => {
              const isCurrentUser = message.sender_id === currentUserId;
              const isAssistant = message.role === 'assistant';
              
              return (
                <div
                  key={message.id}
                  className={`flex ${isCurrentUser ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] sm:max-w-[70%] rounded-lg p-2.5 sm:p-3 ${
                      isAssistant
                        ? 'bg-purple-100 dark:bg-purple-900/30 text-gray-900 dark:text-gray-100'
                        : isCurrentUser
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100'
                    }`}
                  >
                    {!isCurrentUser && !isAssistant && (
                      <p className="text-xs font-medium mb-1 opacity-70">
                        {getMemberEmail(message.sender_id)}
                      </p>
                    )}
                    {isAssistant && (
                      <p className="text-xs font-medium mb-1 flex items-center">
                        <Sparkles size={12} className="mr-1" />
                        Assistant
                      </p>
                    )}
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown 
                        remarkPlugins={[remarkGfm]}
                        components={{
                          table: ({ children }) => (
                            <table className="min-w-full border-collapse border border-slate-300 dark:border-slate-600 my-2 text-sm">
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
                            <p className="mb-2 last:mb-0 text-sm">{children}</p>
                          ),
                          ul: ({ children }) => (
                            <ul className="list-disc list-inside mb-2 text-sm">{children}</ul>
                          ),
                          ol: ({ children }) => (
                            <ol className="list-decimal list-inside mb-2 text-sm">{children}</ol>
                          ),
                          li: ({ children }) => (
                            <li className="mb-1">{children}</li>
                          ),
                          code: ({ children, className }) => {
                            const isInline = !className;
                            return isInline ? (
                              <code className="bg-slate-200 dark:bg-slate-700 px-1 py-0.5 rounded text-xs">{children}</code>
                            ) : (
                              <code className={className}>{children}</code>
                            );
                          },
                          pre: ({ children }) => (
                            <pre className="bg-slate-200 dark:bg-slate-700 p-2 rounded overflow-x-auto text-xs my-2">{children}</pre>
                          ),
                        }}
                      >
                        {message.content}
                      </ReactMarkdown>
                    </div>
                    <p className={`text-xs mt-1 ${
                      isCurrentUser ? 'opacity-70' : 'text-gray-500 dark:text-gray-400'
                    }`}>
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              );
            })
          )}
          
          {/* Typing indicator */}
          {typingUsers.length > 0 && (
            <div className="flex items-center text-sm text-gray-500 dark:text-gray-400">
              <div className="flex space-x-1 mr-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              {typingUsers.map(id => getMemberEmail(id)).join(', ')} typing...
            </div>
          )}
          
          {/* Agent thinking indicator - only show when not streaming */}
          {agentStatus.isThinking && !streamingMessage && (
            <div className="flex items-center text-sm text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20 rounded-lg p-3">
              <div className="flex space-x-1 mr-3">
                <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" />
                <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
              </div>
              <Sparkles size={16} className="mr-2 animate-spin" />
              <span>Agent is thinking... {agentStatus.message}</span>
            </div>
          )}

          {/* Streaming agent response */}
          {streamingMessage && streamingMessage.content && (
            <div className="flex justify-start">
              <div className="max-w-[85%] sm:max-w-[70%] rounded-lg p-2.5 sm:p-3 bg-purple-100 dark:bg-purple-900/30 text-gray-900 dark:text-gray-100">
                <p className="text-xs font-medium mb-1 flex items-center">
                  <Sparkles size={12} className="mr-1" />
                  Assistant
                  {!streamingMessage.isComplete && (
                    <span className="ml-2 inline-flex">
                      <span className="w-1 h-1 bg-purple-500 rounded-full animate-pulse mx-0.5" />
                      <span className="w-1 h-1 bg-purple-500 rounded-full animate-pulse mx-0.5" style={{ animationDelay: '150ms' }} />
                      <span className="w-1 h-1 bg-purple-500 rounded-full animate-pulse mx-0.5" style={{ animationDelay: '300ms' }} />
                    </span>
                  )}
                </p>
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {streamingMessage.content}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Events sidebar - overlay on mobile */}
        {showEvents && (
          <>
            {/* Mobile overlay backdrop */}
            <div 
              className="fixed inset-0 bg-black/50 z-40 md:hidden"
              onClick={() => setShowEvents(false)}
            />
            <div className="fixed md:relative inset-y-0 right-0 z-50 md:z-auto w-80 max-w-[85vw] border-l border-gray-200 dark:border-gray-700 overflow-y-auto bg-white dark:bg-slate-900 md:bg-transparent">
              <div className="p-4">
                {/* Mobile close button */}
                <div className="flex md:hidden items-center justify-between mb-3">
                  <span className="font-semibold text-sm">Events & Suggestions</span>
                  <button
                    onClick={() => setShowEvents(false)}
                    className="p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                  >
                    ✕
                  </button>
                </div>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
                Upcoming Events
              </h3>
              {upcomingEvents.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  No events detected yet
                </p>
              ) : (
                <div className="space-y-3">
                  {upcomingEvents.map((event) => (
                    <div
                      key={event.id}
                      className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg"
                    >
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {event.title}
                      </p>
                      {(event.event_datetime_local || event.event_datetime) && (
                        <p className="text-xs text-blue-600 dark:text-blue-400 mt-1 flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {event.event_datetime_local || event.event_datetime}
                        </p>
                      )}
                      {event.location && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          📍 {event.location}
                        </p>
                      )}
                      {event.description && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          {event.description}
                        </p>
                      )}
                      <div className="flex items-center flex-wrap gap-1 mt-2 text-xs text-gray-500 dark:text-gray-400">
                        <span className={`px-2 py-0.5 rounded-full ${
                          event.event_type === 'meeting' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' :
                          event.event_type === 'deadline' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' :
                          event.event_type === 'activity' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
                          'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                        }`}>
                          {event.event_type}
                        </span>
                        {!event.is_confirmed && (
                          <button
                            onClick={async () => {
                              try {
                                await api.updateEvent(event.group_id, event.id, { is_confirmed: true });
                                // Refresh events from the store
                                useGroupStore.getState().fetchEvents();
                              } catch (err) {
                                console.error('Failed to confirm event:', err);
                              }
                            }}
                            className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50 transition-colors cursor-pointer"
                          >
                            Confirm
                          </button>
                        )}
                        {event.is_confirmed && (event.google_sync_status === 'pending' || event.google_sync_status === 'failed') && event.event_datetime && (
                          <button
                            onClick={async (e) => {
                              e.stopPropagation();
                              try {
                                await api.syncEvent(group.id, event.id);
                                useGroupStore.getState().fetchEvents();
                              } catch (err) {
                                console.error('Failed to sync event:', err);
                                alert('Failed to sync event. Make sure your Google Calendar is connected in Settings.');
                              }
                            }}
                            className="px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 transition-colors cursor-pointer flex items-center gap-1"
                            title="Sync to your Google Calendar"
                          >
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                            {event.google_sync_status === 'failed' ? 'Retry sync' : 'Sync'}
                          </button>
                        )}
                        {event.is_confirmed && (event.google_sync_status === 'pending' || event.google_sync_status === 'failed') && !event.event_datetime && (
                          <span className="text-xs text-gray-400" title="Add a date/time to sync this event">
                            No time set
                          </span>
                        )}
                        {event.google_sync_status === 'synced' && (
                          <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 flex items-center gap-1">
                            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                            </svg>
                            synced
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {suggestions.length > 0 && (
                <>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mt-6 mb-3">
                    Suggestions
                  </h3>
                  <div className="space-y-3">
                    {suggestions.slice(0, 3).map((suggestion, idx) => (
                      <div
                        key={idx}
                        className="p-3 bg-gradient-to-r from-purple-50 to-blue-50 dark:from-purple-900/20 dark:to-blue-900/20 rounded-lg"
                      >
                        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                          {suggestion.title}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          {suggestion.reason}
                        </p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
          </>
        )}
      </div>

      {/* Connection error banner */}
      {connectionError && (
        <div className="px-4 py-2 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 text-sm">
          Connection error: {connectionError}
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-2 sm:p-4 border-t border-gray-200 dark:border-gray-700 safe-area-inset-bottom">
        <div className="flex items-end space-x-2">
          <textarea
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={isConnected ? "Type a message..." : "Connecting..."}
            rows={1}
            disabled={!isConnected}
            className="flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 sm:px-4 py-2.5 sm:py-2 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ fontSize: '16px' }} // Prevent iOS zoom on focus
          />
          <button
            type="submit"
            disabled={!input.trim() || !isConnected}
            className="p-2.5 sm:p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 active:bg-blue-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors touch-manipulation"
          >
            <Send size={20} />
          </button>
        </div>
      </form>
    </div>
  );
}

import { useCallback, useRef } from 'react';
import { useChatStore } from '../stores/chatStore';
import { createSSEConnection } from '../lib/sse';
import { api } from '../lib/api';
import type { Message, ConversationDetail } from '../types';

export function useChat() {
  const {
    setConversationId,
    addMessage,
    clearMessages,
    setSuggestions,
    setStreaming,
    clearTraceNodes,
    handleStreamEvent,
    setConversations,
    updateLastMessage,
  } = useChatStore();
  
  const abortRef = useRef<{ abort: () => void } | null>(null);
  
  const sendMessage = useCallback(async (content: string) => {
    // Abort any existing connection
    abortRef.current?.abort();
    
    // Get current conversation ID directly from store (avoid stale closure)
    const currentConversationId = useChatStore.getState().conversationId;
    
    // Clear trace nodes and start streaming
    clearTraceNodes();
    setStreaming(true);
    setSuggestions([]);
    
    // Add user message optimistically
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    };
    addMessage(userMessage);
    
    // Add placeholder for assistant response
    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    addMessage(assistantMessage);
    
    // Create SSE connection
    abortRef.current = createSSEConnection(content, currentConversationId, {
      onEvent: (event) => {
        handleStreamEvent(event);
        
        // Update conversation ID from response (for new conversations)
        if (event.event_type === 'response' && event.data?.conversation_id) {
          const newConvId = event.data.conversation_id as string;
          if (newConvId !== currentConversationId) {
            setConversationId(newConvId);
          }
        }
      },
      onError: (error) => {
        console.error('SSE error:', error);
        setStreaming(false);
        updateLastMessage(
          error?.message || 'Connection lost or server error. Please try again.'
        );
      },
      onComplete: () => {
        setStreaming(false);
        // Refresh conversations list
        api.listConversations().then(setConversations).catch(console.error);
      },
    });
  }, [
    addMessage,
    clearTraceNodes,
    handleStreamEvent,
    setConversationId,
    setStreaming,
    setSuggestions,
    setConversations,
    updateLastMessage,
  ]);
  
  const loadConversation = useCallback(async (id: string) => {
    // Set conversation ID immediately (before API call) so messages go to the right place
    setConversationId(id);
    clearMessages();
    clearTraceNodes();
    
    try {
      const conversation = await api.getConversation(id);
      
      // Convert and add messages
      conversation.messages.forEach((msg: ConversationDetail['messages'][0]) => {
        const message: Message = {
          id: msg.id,
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          timestamp: new Date(msg.timestamp),
        };
        addMessage(message);
      });
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  }, [setConversationId, clearMessages, clearTraceNodes, addMessage]);
  
  const startNewConversation = useCallback(() => {
    setConversationId(null);
    clearMessages();
    clearTraceNodes();
    setSuggestions([]);
  }, [setConversationId, clearMessages, clearTraceNodes, setSuggestions]);
  
  const abortStream = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, [setStreaming]);
  
  return {
    sendMessage,
    loadConversation,
    startNewConversation,
    abortStream,
  };
}

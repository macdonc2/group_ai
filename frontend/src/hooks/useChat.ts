import { useCallback, useRef, useEffect } from 'react';
import { useChatStore } from '../stores/chatStore';
import { createSSEConnection } from '../lib/sse';
import { api } from '../lib/api';
import { useThemeStore } from '../stores/themeStore';
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
  const initialLoadDone = useRef(false);
  
  // Load persisted conversation on mount (if conversationId exists but messages are empty)
  useEffect(() => {
    if (initialLoadDone.current) return;
    
    // Check if we have a persisted conversationId but no messages loaded
    const state = useChatStore.getState();
    if (state.conversationId && state.messages.length === 0) {
      initialLoadDone.current = true;
      // Load the persisted conversation
      api.getConversation(state.conversationId)
        .then((conversation) => {
          conversation.messages.forEach((msg: ConversationDetail['messages'][0]) => {
            const message: Message = {
              id: msg.id,
              role: msg.role as 'user' | 'assistant',
              content: msg.content,
              timestamp: new Date(msg.timestamp),
            };
            useChatStore.getState().addMessage(message);
          });
        })
        .catch((error) => {
          console.error('Failed to load persisted conversation:', error);
          // Clear the invalid conversation ID
          useChatStore.getState().setConversationId(null);
        });
    } else {
      initialLoadDone.current = true;
    }
  }, []);
  
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
    
    // Create SSE connection (in the active wrestler's voice, if any)
    const persona = useThemeStore.getState().wrestler;
    abortRef.current = createSSEConnection(content, currentConversationId, {
      onEvent: (event) => {
        handleStreamEvent(event);
        
        // Update conversation ID as early as possible (conversation_created
        // fires right after the backend creates the conversation, before the
        // workflow runs; response fires at the end as a fallback).
        if (
          (event.event_type === 'conversation_created' || event.event_type === 'response')
          && event.data?.conversation_id
        ) {
          const newConvId = event.data.conversation_id as string;
          const currentId = useChatStore.getState().conversationId;
          if (newConvId !== currentId) {
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
    }, persona);
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

import type { StreamEvent } from '../types';
import { useAuthStore } from '../stores/authStore';

export interface SSEOptions {
  onEvent: (event: StreamEvent) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

export function createSSEConnection(
  message: string,
  conversationId: string | null,
  options: SSEOptions
): { abort: () => void } {
  const params = new URLSearchParams({ message });
  if (conversationId) {
    params.append('conversation_id', conversationId);
  }
  
  // Add auth token - EventSource API cannot send custom headers
  const token = useAuthStore.getState().token;
  if (token) {
    params.append('token', token);
  }

  const url = `/api/v1/agent/chat/stream?${params.toString()}`;
  
  const eventSource = new EventSource(url);
  
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as StreamEvent;
      options.onEvent(data);
      
      // Close only on final response or error (NOT on response_chunk)
      if (data.event_type === 'response' || data.event_type === 'error') {
        eventSource.close();
        options.onComplete?.();
      }
      // response_chunk events keep the connection open for streaming
    } catch (error) {
      console.error('Failed to parse SSE event:', error);
    }
  };
  
  eventSource.onerror = (error) => {
    console.error('SSE error:', error);
    eventSource.close();
    options.onError?.(new Error('Connection lost'));
    options.onComplete?.();
  };

  return {
    abort: () => {
      eventSource.close();
      options.onComplete?.();
    },
  };
}

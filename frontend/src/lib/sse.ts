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
  options: SSEOptions,
  persona?: string | null
): { abort: () => void } {
  const params = new URLSearchParams({ message });
  if (conversationId) {
    params.append('conversation_id', conversationId);
  }
  if (persona && persona !== 'none') {
    params.append('persona', persona);
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


// ---------------------------------------------------------------------------
// Generic SSE (used by Deep Research). The chat helper above is unchanged.
// ---------------------------------------------------------------------------

export interface GenericSSEOptions<E> {
  onEvent: (event: E) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
  /** event_type values that end the stream. */
  terminalEvents: string[];
}

export function createGenericSSE<E extends { event_type: string }>(
  path: string,
  params: Record<string, string>,
  options: GenericSSEOptions<E>
): { abort: () => void } {
  const search = new URLSearchParams(params);
  const token = useAuthStore.getState().token;
  if (token) search.append('token', token);

  const eventSource = new EventSource(`${path}?${search.toString()}`);
  let closed = false;
  const finish = () => {
    if (closed) return;
    closed = true;
    eventSource.close();
    options.onComplete?.();
  };

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as E;
      options.onEvent(data);
      if (options.terminalEvents.includes(data.event_type)) finish();
    } catch (error) {
      console.error('Failed to parse SSE event:', error);
    }
  };

  eventSource.onerror = () => {
    if (closed) return;
    closed = true;
    eventSource.close();
    options.onError?.(new Error('Connection lost'));
    options.onComplete?.();
  };

  return { abort: finish };
}

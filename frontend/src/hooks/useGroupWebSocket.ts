import { useState, useEffect, useCallback, useRef } from 'react';
import type { GroupMessage, ExtractedEvent, GroupWSMessage, GroupWSMessageType } from '../types';

interface UseGroupWebSocketOptions {
  groupId: string;
  conversationId: string;
  userId: string;
  onMessage?: (message: GroupMessage) => void;
  onEventExtracted?: (event: Partial<ExtractedEvent>) => void;
  onError?: (error: string) => void;
}

interface AgentStatus {
  isThinking: boolean;
  message: string | null;
}

interface StreamingMessage {
  id: string;
  content: string;
  isComplete: boolean;
}

interface UseGroupWebSocketReturn {
  isConnected: boolean;
  messages: GroupMessage[];
  typingUsers: string[];
  onlineUsers: string[];
  agentStatus: AgentStatus;
  streamingMessage: StreamingMessage | null;
  sendMessage: (content: string) => void;
  setTyping: (isTyping: boolean) => void;
  error: string | null;
}

// Module-level WebSocket management to prevent React lifecycle issues
let globalWs: WebSocket | null = null;
let globalConnectionKey = '';
let globalReconnectTimeout: ReturnType<typeof setTimeout> | null = null;

export function useGroupWebSocket({
  groupId,
  conversationId,
  userId,
  onMessage,
  onEventExtracted,
  onError,
}: UseGroupWebSocketOptions): UseGroupWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [typingUsers, setTypingUsers] = useState<string[]>([]);
  const [onlineUsers, setOnlineUsers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>({ isThinking: false, message: null });
  const [streamingMessage, setStreamingMessage] = useState<StreamingMessage | null>(null);
  
  // Store callbacks in refs
  const callbacksRef = useRef({ onMessage, onEventExtracted, onError });
  callbacksRef.current = { onMessage, onEventExtracted, onError };
  
  // Store state setters in refs for the message handler
  const settersRef = useRef({ setMessages, setTypingUsers, setOnlineUsers, setError, setAgentStatus, setIsConnected, setStreamingMessage });

  useEffect(() => {
    if (!groupId || !conversationId || !userId) {
      setIsConnected(false);
      return;
    }

    const connectionKey = `${groupId}:${conversationId}:${userId}`;
    
    // Already connected to this endpoint
    if (connectionKey === globalConnectionKey && globalWs?.readyState === WebSocket.OPEN) {
      setIsConnected(true);
      return;
    }
    
    // Close existing connection if connecting to different endpoint
    if (globalWs && globalConnectionKey !== connectionKey) {
      globalWs.close(1000, 'Switching endpoints');
      globalWs = null;
    }
    
    // Clear any pending reconnect
    if (globalReconnectTimeout) {
      clearTimeout(globalReconnectTimeout);
      globalReconnectTimeout = null;
    }
    
    globalConnectionKey = connectionKey;
    
    // Clear state for new connection
    setMessages([]);
    setTypingUsers([]);
    setOnlineUsers([]);
    setError(null);
    setAgentStatus({ isThinking: false, message: null });
    setStreamingMessage(null);
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/groups/${groupId}/conversations/${conversationId}/ws?user_id=${userId}`;
    
    console.log('[WS] Connecting to:', wsUrl);
    const ws = new WebSocket(wsUrl);
    globalWs = ws;
    
    ws.onopen = () => {
      if (ws !== globalWs) return; // Stale connection
      console.log('[WS] Connected');
      settersRef.current.setIsConnected(true);
      settersRef.current.setError(null);
    };
    
    ws.onclose = (event) => {
      if (ws !== globalWs) return; // Stale connection
      console.log('[WS] Closed:', event.code, event.reason);
      settersRef.current.setIsConnected(false);
      
      // Don't reconnect on normal close or access denied
      if (event.code === 1000 || event.code === 4003 || event.code === 4004) {
        return;
      }
      
      // Reconnect after delay
      globalReconnectTimeout = setTimeout(() => {
        if (globalConnectionKey === connectionKey && (!globalWs || globalWs.readyState === WebSocket.CLOSED)) {
          console.log('[WS] Attempting reconnect...');
          globalWs = null;
          globalConnectionKey = ''; // Force reconnect
        }
      }, 5000);
    };
    
    ws.onerror = (err) => {
      if (ws !== globalWs) return;
      console.error('[WS] Error:', err);
      settersRef.current.setError('WebSocket connection error');
    };
    
    ws.onmessage = (event) => {
      if (ws !== globalWs) return;
      try {
        const data: GroupWSMessage = JSON.parse(event.data);
        handleMessage(data, callbacksRef.current, settersRef.current);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
    
    // Cleanup only on unmount, not on re-renders
    return () => {
      // Don't close the connection - let it persist
      // Only the module-level globalWs management handles closing
    };
  }, [groupId, conversationId, userId]);
  
  // Cleanup on actual component unmount
  useEffect(() => {
    return () => {
      console.log('[WS] Component unmounting');
      if (globalWs) {
        globalWs.close(1000, 'Component unmounting');
        globalWs = null;
        globalConnectionKey = '';
      }
      if (globalReconnectTimeout) {
        clearTimeout(globalReconnectTimeout);
        globalReconnectTimeout = null;
      }
    };
  }, []);

  const sendMessage = useCallback((content: string) => {
    if (globalWs?.readyState === WebSocket.OPEN) {
      console.log('[WS] Sending message:', content.slice(0, 50));
      globalWs.send(JSON.stringify({
        type: 'message',
        data: { content },
      }));
    } else {
      console.warn('[WS] Cannot send - not connected');
    }
  }, []);

  const setTyping = useCallback((isTyping: boolean) => {
    if (globalWs?.readyState === WebSocket.OPEN) {
      globalWs.send(JSON.stringify({
        type: isTyping ? 'typing' : 'stop_typing',
        data: {},
      }));
    }
  }, []);

  return {
    isConnected,
    messages,
    typingUsers: typingUsers.filter(id => id !== userId),
    onlineUsers,
    agentStatus,
    streamingMessage,
    sendMessage,
    setTyping,
    error,
  };
}

// Message handler outside component to avoid re-creation
function handleMessage(
  data: GroupWSMessage,
  callbacks: { onMessage?: (m: GroupMessage) => void; onEventExtracted?: (e: Partial<ExtractedEvent>) => void; onError?: (e: string) => void },
  setters: { setMessages: React.Dispatch<React.SetStateAction<GroupMessage[]>>; setTypingUsers: React.Dispatch<React.SetStateAction<string[]>>; setOnlineUsers: React.Dispatch<React.SetStateAction<string[]>>; setError: React.Dispatch<React.SetStateAction<string | null>>; setAgentStatus: React.Dispatch<React.SetStateAction<AgentStatus>>; setIsConnected: React.Dispatch<React.SetStateAction<boolean>>; setStreamingMessage: React.Dispatch<React.SetStateAction<StreamingMessage | null>> }
) {
  switch (data.type as GroupWSMessageType) {
    case 'new_message': {
      const newMessage: GroupMessage = {
        id: data.data.message_id as string,
        sender_id: data.data.sender_id as string,
        role: (data.data.role as string) === 'assistant' ? 'assistant' : 'user',
        content: data.data.content as string,
        timestamp: data.timestamp,
        tool_calls: (data.data.tool_calls as Array<{ name: string; arguments: Record<string, unknown>; result?: string }>) || [],
      };
      // Clear streaming message when final message arrives
      setters.setStreamingMessage(null);
      setters.setMessages((prev) => [...prev, newMessage]);
      callbacks.onMessage?.(newMessage);
      break;
    }

    case 'user_joined':
      setters.setOnlineUsers(data.data.online_users as string[]);
      break;

    case 'user_left':
      setters.setOnlineUsers(data.data.online_users as string[]);
      break;

    case 'typing_update':
      setters.setTypingUsers(data.data.typing_users as string[]);
      break;

    case 'event_extracted':
      callbacks.onEventExtracted?.(data.data as Partial<ExtractedEvent>);
      break;

    case 'agent_thinking': {
      const status = data.data.status as string;
      const nodeName = data.data.node_name as string | null;
      if (status === 'thinking') {
        setters.setAgentStatus({ isThinking: true, message: nodeName || 'Processing...' });
      } else if (status === 'idle' || status === 'error') {
        setters.setAgentStatus({ isThinking: false, message: null });
      } else if (status === 'generating') {
        // Agent is generating response - streaming will begin
        setters.setAgentStatus({ isThinking: true, message: 'Generating response...' });
      }
      break;
    }

    case 'agent_chunk': {
      // Streaming chunk received - accumulate content
      const messageId = data.data.message_id as string;
      const chunk = data.data.chunk as string;
      setters.setStreamingMessage((prev) => {
        if (!prev || prev.id !== messageId) {
          // New streaming message
          return { id: messageId, content: chunk, isComplete: false };
        }
        // Append to existing message
        return { ...prev, content: prev.content + chunk };
      });
      // Update agent status to show we're receiving
      setters.setAgentStatus({ isThinking: true, message: 'Generating response...' });
      break;
    }

    case 'agent_complete': {
      // Streaming complete - mark as done
      const messageId = data.data.message_id as string;
      setters.setStreamingMessage((prev) => {
        if (prev && prev.id === messageId) {
          return { ...prev, isComplete: true };
        }
        return prev;
      });
      // Clear agent thinking status
      setters.setAgentStatus({ isThinking: false, message: null });
      break;
    }

    case 'error': {
      const errorMsg = data.data.message as string;
      setters.setError(errorMsg);
      callbacks.onError?.(errorMsg);
      break;
    }

    default:
      console.log('Unknown WebSocket message type:', data.type);
  }
}

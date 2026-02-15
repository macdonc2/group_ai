import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message, Suggestion, TraceNode, ConversationListItem, StreamEvent } from '../types';

interface ChatState {
  // Current conversation
  conversationId: string | null;
  messages: Message[];
  suggestions: Suggestion[];
  
  // Trace/workflow state
  traceNodes: TraceNode[];
  isStreaming: boolean;
  
  // Conversations list
  conversations: ConversationListItem[];
  
  // UI state
  isSidebarOpen: boolean;
  isTracePanelOpen: boolean;
  
  // Actions
  setConversationId: (id: string | null) => void;
  addMessage: (message: Message) => void;
  updateLastMessage: (content: string) => void;
  setSuggestions: (suggestions: Suggestion[]) => void;
  clearMessages: () => void;
  
  // Trace actions
  setStreaming: (isStreaming: boolean) => void;
  addTraceNode: (node: TraceNode) => void;
  updateTraceNode: (name: string, updates: Partial<TraceNode>) => void;
  clearTraceNodes: () => void;
  handleStreamEvent: (event: StreamEvent) => void;
  
  // Conversation list actions
  setConversations: (conversations: ConversationListItem[]) => void;
  addConversation: (conversation: ConversationListItem) => void;
  removeConversation: (id: string) => void;
  
  // UI actions
  toggleSidebar: () => void;
  toggleTracePanel: () => void;
}

// FSM workflow nodes in order
const WORKFLOW_NODES = [
  'ReceiveInput',
  'AnalyzeIntent',
  'UpdateKnowledge',
  'CheckPlan',
  'CreatePlan',
  'ExecutePlan',
  'SelectTool',
  'ExecuteTool',
  'EvaluateResult',
  'GenerateResponse',
  'FinalizeKnowledge',
];

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      // Initial state
      conversationId: null,
      messages: [],
      suggestions: [],
      traceNodes: [],
      isStreaming: false,
      conversations: [],
      isSidebarOpen: true,
      isTracePanelOpen: true,

      // Actions
      setConversationId: (id) => set({ conversationId: id }),
  
  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message],
  })),
  
  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content,
      };
    }
    return { messages };
  }),
  
  setSuggestions: (suggestions) => set({ suggestions }),
  
  clearMessages: () => set({ messages: [], suggestions: [] }),
  
  // Trace actions
  setStreaming: (isStreaming) => set({ isStreaming }),
  
  addTraceNode: (node) => set((state) => ({
    traceNodes: [...state.traceNodes, node],
  })),
  
  updateTraceNode: (name, updates) => set((state) => ({
    traceNodes: state.traceNodes.map((node) =>
      node.name === name ? { ...node, ...updates } : node
    ),
  })),
  
  clearTraceNodes: () => set({ traceNodes: [] }),
  
  handleStreamEvent: (event) => {
    const state = get();
    
    switch (event.event_type) {
      case 'node_start':
        if (event.node_name) {
          // Initialize all nodes as pending on first event
          if (state.traceNodes.length === 0) {
            const initialNodes: TraceNode[] = WORKFLOW_NODES.map((name) => ({
              name,
              status: 'pending',
              message: '',
            }));
            set({ traceNodes: initialNodes });
          }
          
          // Update the specific node to running
          set((s) => ({
            traceNodes: s.traceNodes.map((node) =>
              node.name === event.node_name
                ? {
                    ...node,
                    status: 'running',
                    message: event.message,
                    startTime: event.timestamp,
                  }
                : node
            ),
          }));
        }
        break;
        
      case 'node_complete':
      case 'tool_result':
        if (event.node_name) {
          set((s) => ({
            traceNodes: s.traceNodes.map((node) =>
              node.name === event.node_name
                ? {
                    ...node,
                    status: 'complete',
                    message: event.message,
                    data: event.data ?? undefined,
                    endTime: event.timestamp,
                  }
                : node
            ),
          }));
        }
        break;
        
      case 'node_skipped':
        if (event.node_name) {
          set((s) => ({
            traceNodes: s.traceNodes.map((node) =>
              node.name === event.node_name
                ? {
                    ...node,
                    status: 'skipped',
                    message: event.message,
                  }
                : node
            ),
          }));
        }
        break;
        
      case 'response_chunk':
        // Streaming chunk - append to last assistant message
        if (event.message) {
          const messages = get().messages;
          const lastMessage = messages[messages.length - 1];
          if (lastMessage && lastMessage.role === 'assistant') {
            // Append chunk to existing content
            set({
              messages: messages.map((msg, idx) =>
                idx === messages.length - 1
                  ? { ...msg, content: msg.content + event.message }
                  : msg
              ),
            });
          }
        }
        break;
        
      case 'response':
        // Final response - update suggestions
        if (event.data) {
          const suggestions = (event.data.suggestions as Suggestion[]) || [];
          set({ suggestions, isStreaming: false });
          
          // Update last assistant message with final response (in case we missed chunks)
          const response = event.data.response as string;
          if (response) {
            get().updateLastMessage(response);
          }
        }
        break;
        
      case 'error': {
        const errMsg = event.message || 'An error occurred. Please try again.';
        set({ isStreaming: false });
        // Show error in chat bubble so user always sees it (even if no trace nodes yet)
        get().updateLastMessage(errMsg);
        // Mark current running node as error in trace, or add one error node if none yet
        set((s) => ({
          traceNodes: s.traceNodes.length > 0
            ? s.traceNodes.map((node) =>
                node.status === 'running'
                  ? { ...node, status: 'error', message: event.message }
                  : node
              )
            : [
                {
                  name: 'Error',
                  status: 'error' as const,
                  message: errMsg,
                },
              ],
        }));
        break;
      }
    }
  },
  
  // Conversation list actions
  setConversations: (conversations) => set({ conversations }),
  
  addConversation: (conversation) => set((state) => ({
    conversations: [conversation, ...state.conversations],
  })),
  
  removeConversation: (id) => set((state) => ({
    conversations: state.conversations.filter((c) => c.id !== id),
  })),
  
  // UI actions
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  toggleTracePanel: () => set((state) => ({ isTracePanelOpen: !state.isTracePanelOpen })),
    }),
    {
      name: 'chat-storage',
      // Only persist conversationId and UI preferences - not transient state
      partialize: (state) => ({
        conversationId: state.conversationId,
        isSidebarOpen: state.isSidebarOpen,
        isTracePanelOpen: state.isTracePanelOpen,
      }),
    }
  )
);

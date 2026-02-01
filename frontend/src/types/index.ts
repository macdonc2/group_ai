// API Types

export interface Suggestion {
  title: string;
  description: string;
  relevance_score: number;
  action_type: string | null;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  messageCount: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

// SSE Event Types

export type TraceEventType = 
  | 'node_start' 
  | 'node_complete' 
  | 'node_skipped'
  | 'tool_result' 
  | 'response_chunk'
  | 'response' 
  | 'error';

export interface StreamEvent {
  event_type: TraceEventType;
  node_name: string | null;
  message: string;
  data: Record<string, unknown> | null;
  timestamp: number;
}

export type TraceNodeStatus = 'pending' | 'running' | 'complete' | 'skipped' | 'error';

export interface TraceNode {
  name: string;
  status: TraceNodeStatus;
  message: string;
  data?: Record<string, unknown>;
  startTime?: number;
  endTime?: number;
}

// API Response Types

export interface AgentResponse {
  response: string;
  conversation_id: string;
  suggestions: Suggestion[];
  plan_created: boolean;
  plan_updated: boolean;
  tools_used: string[];
}

export interface ConversationListItem {
  id: string;
  user_id: string;
  title: string | null;
  summary: string | null;
  message_count: number;
  is_archived: boolean;
  active_plan_id: string | null;
  created_at: string;
  updated_at: string;
}

// Group Types

export interface Group {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface GroupMember {
  id: string;
  user_id: string;
  user_email: string | null;
  role: 'owner' | 'member';
  sharing_enabled: boolean;
  joined_at: string;
  last_seen_at: string | null;
}

export interface GroupDetail extends Group {
  members: GroupMember[];
}

export interface GroupConversation {
  id: string;
  group_id: string;
  title: string | null;
  message_count: number;
  participant_count: number;
  created_at: string;
  updated_at: string;
}

export interface GroupMessage {
  id: string;
  sender_id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  tool_calls: ToolCall[];
}

export interface GroupConversationDetail extends GroupConversation {
  messages: GroupMessage[];
}

export interface ExtractedEvent {
  id: string;
  group_id: string;
  title: string;
  description: string | null;
  event_type: 'meeting' | 'deadline' | 'activity' | 'obligation';
  event_datetime: string | null;
  event_datetime_local: string | null;  // Formatted in user's timezone
  timezone: string;  // User's timezone (e.g., "America/Chicago")
  location: string | null;
  participant_ids: string[];
  confidence: number;
  is_confirmed: boolean;
  created_at: string;
  // Google Calendar sync
  google_event_id: string | null;
  google_sync_status: 'pending' | 'synced' | 'failed' | 'not_enabled';
}

export interface SocialSuggestion {
  title: string;
  description: string;
  suggested_participants: string[];
  reason: string;
  event_type: string | null;
}

export interface GroupSummary {
  themes: string[];
  upcoming_events: ExtractedEvent[];
  social_suggestions: SocialSuggestion[];
  active_member_ids: string[];
  message_count_week: number;
}

// WebSocket Message Types for Group Chat

export type GroupWSMessageType = 
  | 'message'
  | 'typing'
  | 'stop_typing'
  | 'new_message'
  | 'user_joined'
  | 'user_left'
  | 'typing_update'
  | 'event_extracted'
  | 'agent_thinking'
  | 'agent_chunk'
  | 'agent_complete'
  | 'error';

export interface GroupWSMessage {
  type: GroupWSMessageType;
  data: Record<string, unknown>;
  timestamp: string;
  sender_id: string | null;
}

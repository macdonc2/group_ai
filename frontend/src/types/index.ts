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
  /** Wrestler persona this conversation was last spoken in (null = plain). */
  persona?: string | null;
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
  | 'conversation_created'
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
  /** Wrestler persona this conversation was last spoken in (null = plain). */
  persona?: string | null;
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


// Deep Research Types

export type LaneName = 'academic' | 'practical' | 'empirical';

export type ResearchStatus =
  | 'queued' | 'running' | 'synthesizing' | 'writing' | 'narrating'
  | 'complete' | 'failed' | 'interrupted';

export interface ResearchListItem {
  id: string;
  question: string;
  title: string | null;
  status: ResearchStatus;
  phase: string;
  created_at: string;
  completed_at: string | null;
  has_audio: boolean;
  figures: number;
  depth?: number;
  error: string | null;
}

export interface ResearchSource {
  id: string;
  lane: LaneName;
  title: string;
  url: string | null;
  authors: string[];
  year: number | null;
  venue: string | null;
  ref: number | null;
}

export interface ResearchFigure {
  ordinal: number;
  caption: string;
  source_ids: string[];
  origin?: 'generated' | 'source';
  source_url?: string | null;
  source_title?: string | null;
}

export interface LaneProgress {
  status: 'pending' | 'running' | 'complete' | 'error';
  step: string;
  round?: number;
  queries: number;
  sources: number;
  findings: number;
  tables: number;
  error: string | null;
}

export interface ResearchProgress {
  phase: string;
  depth?: number;
  lanes: Record<LaneName, LaneProgress>;
  figures: number;
  has_audio: boolean;
}

export interface ResearchDetail extends ResearchListItem {
  tldr: string | null;
  report_markdown: string | null;
  progress: ResearchProgress;
  model: string;
  sources: ResearchSource[];
  figure_list: ResearchFigure[];
}

/** A generic SSE event; research events use their own event_type vocabulary. */
export interface ResearchStreamEvent {
  event_type: string;
  node_name: string | null;
  message: string;
  data: Record<string, unknown> | null;
  timestamp: number;
}

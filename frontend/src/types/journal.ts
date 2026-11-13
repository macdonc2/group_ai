export type JournalMemoryStatus = 'pending' | 'done' | 'failed' | 'skipped';

export interface JournalSuggestion {
  id: string;
  title: string;
  when: string;
  location: string | null;
  status: 'pending' | 'added' | 'dismissed';
}

export interface JournalEntry {
  id: string;
  /** The day the entry is filed under, YYYY-MM-DD, as decided by the server in the user's timezone. */
  date: string;
  body: string;
  memory_status: JournalMemoryStatus;
  suggestions: JournalSuggestion[];
  created_at: string;
  updated_at: string;
}

export interface JournalDays {
  today: string;
  timezone: string;
  month: string;
  days: Record<string, number>;
}

export interface JournalMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tools_used: string[];
  created_at: string;
}

export interface JournalStreamEvent {
  event_type: string;
  node_name: string | null;
  message: string;
  data: Record<string, unknown> | null;
  timestamp: number;
}

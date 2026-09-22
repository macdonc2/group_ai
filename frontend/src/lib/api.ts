import type { 
  AgentResponse, 
  ConversationListItem, 
  ConversationDetail,
  Group,
  GroupDetail,
  GroupConversation,
  GroupConversationDetail,
  ExtractedEvent,
  SocialSuggestion,
  GroupSummary,
  ResearchListItem,
  ResearchDetail,
  EvalSuite,
  EvalRunItem,
  EvalRunDetail,
  EvalCaseRow,
  EvalCaseDetail,
  FsmTopology,
  TracedConversation,
  ConversationTrace,
  RunComparison,
} from '../types';
import { useAuthStore } from '../stores/authStore';

const API_BASE = '/api/v1';

class ApiError extends Error {
  status: number;
  
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function getAuthHeaders(): Record<string, string> {
  const token = useAuthStore.getState().token;
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  return {};
}

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    // Handle 401 by clearing auth state
    if (response.status === 401) {
      useAuthStore.getState().logout();
    }
    
    const error = await response.text();
    throw new ApiError(response.status, error);
  }

  // Handle 204 No Content (e.g., DELETE responses)
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const api = {
  // Agent
  chat: async (message: string, conversationId?: string, persona?: string | null): Promise<AgentResponse> => {
    return fetchApi<AgentResponse>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        persona: persona && persona !== 'none' ? persona : undefined,
      }),
    });
  },

  // Conversations
  listConversations: async (): Promise<ConversationListItem[]> => {
    return fetchApi<ConversationListItem[]>('/conversations');
  },

  getConversation: async (id: string): Promise<ConversationDetail> => {
    return fetchApi<ConversationDetail>(`/conversations/${id}`);
  },

  createConversation: async (title?: string): Promise<ConversationListItem> => {
    return fetchApi<ConversationListItem>('/conversations', {
      method: 'POST',
      body: JSON.stringify({ title }),
    });
  },

  /** Remember the wrestler a conversation is spoken in ('none' clears it). */
  setConversationPersona: async (id: string, persona: string): Promise<ConversationListItem> => {
    return fetchApi<ConversationListItem>(`/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ persona }),
    });
  },

  deleteConversation: async (id: string): Promise<void> => {
    await fetchApi(`/conversations/${id}`, {
      method: 'DELETE',
    });
  },

  // Groups
  listGroups: async (): Promise<Group[]> => {
    return fetchApi<Group[]>('/groups');
  },

  getGroup: async (id: string): Promise<GroupDetail> => {
    return fetchApi<GroupDetail>(`/groups/${id}`);
  },

  createGroup: async (name: string, description?: string): Promise<Group> => {
    return fetchApi<Group>('/groups', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    });
  },

  updateGroup: async (id: string, name?: string, description?: string): Promise<Group> => {
    return fetchApi<Group>(`/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name, description }),
    });
  },

  deleteGroup: async (id: string): Promise<void> => {
    await fetchApi(`/groups/${id}`, {
      method: 'DELETE',
    });
  },

  // Group Members
  addGroupMember: async (groupId: string, userId: string): Promise<void> => {
    await fetchApi(`/groups/${groupId}/members`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    });
  },

  removeGroupMember: async (groupId: string, userId: string): Promise<void> => {
    await fetchApi(`/groups/${groupId}/members/${userId}`, {
      method: 'DELETE',
    });
  },

  updateMemberSettings: async (groupId: string, userId: string, sharingEnabled: boolean): Promise<void> => {
    await fetchApi(`/groups/${groupId}/members/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ sharing_enabled: sharingEnabled }),
    });
  },

  // Group Conversations
  listGroupConversations: async (groupId: string): Promise<GroupConversation[]> => {
    return fetchApi<GroupConversation[]>(`/groups/${groupId}/conversations`);
  },

  getGroupConversation: async (groupId: string, conversationId: string): Promise<GroupConversationDetail> => {
    return fetchApi<GroupConversationDetail>(`/groups/${groupId}/conversations/${conversationId}`);
  },

  createGroupConversation: async (groupId: string, title?: string): Promise<GroupConversation> => {
    return fetchApi<GroupConversation>(`/groups/${groupId}/conversations`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    });
  },

  deleteGroupConversation: async (groupId: string, conversationId: string): Promise<void> => {
    await fetchApi(`/groups/${groupId}/conversations/${conversationId}`, {
      method: 'DELETE',
    });
  },

  // Events
  listEvents: async (groupId: string): Promise<ExtractedEvent[]> => {
    return fetchApi<ExtractedEvent[]>(`/groups/${groupId}/events`);
  },

  listUpcomingEvents: async (groupId: string): Promise<ExtractedEvent[]> => {
    return fetchApi<ExtractedEvent[]>(`/groups/${groupId}/events/upcoming`);
  },

  updateEvent: async (groupId: string, eventId: string, updates: Partial<ExtractedEvent>): Promise<ExtractedEvent> => {
    return fetchApi<ExtractedEvent>(`/groups/${groupId}/events/${eventId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  },

  deleteEvent: async (groupId: string, eventId: string): Promise<void> => {
    await fetchApi(`/groups/${groupId}/events/${eventId}`, {
      method: 'DELETE',
    });
  },

  syncEvent: async (groupId: string, eventId: string): Promise<ExtractedEvent> => {
    return fetchApi<ExtractedEvent>(`/groups/${groupId}/events/${eventId}/sync`, {
      method: 'POST',
    });
  },

  // Summary & Social
  getGroupSummary: async (groupId: string): Promise<GroupSummary> => {
    return fetchApi<GroupSummary>(`/groups/${groupId}/summary`);
  },

  getSocialSuggestions: async (groupId: string): Promise<SocialSuggestion[]> => {
    return fetchApi<SocialSuggestion[]>(`/groups/${groupId}/social/suggestions`);
  },

  // User Management (Admin)
  listUsers: async (): Promise<Array<{
    id: string;
    email: string;
    is_active: boolean;
    is_verified: boolean;
    is_superuser: boolean;
    created_at: string;
  }>> => {
    return fetchApi('/auth/users');
  },

  // Search users (any authenticated user - for adding to groups)
  searchUsers: async (): Promise<Array<{
    id: string;
    email: string;
    is_active: boolean;
    is_verified: boolean;
  }>> => {
    return fetchApi('/auth/users/search');
  },

  createUser: async (email: string, password: string): Promise<{
    id: string;
    email: string;
    is_active: boolean;
    is_verified: boolean;
    is_superuser: boolean;
    created_at: string;
  }> => {
    return fetchApi('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, is_superuser: false }),
    });
  },

  verifyUser: async (userId: string): Promise<void> => {
    await fetchApi(`/auth/users/${userId}/verify`, { method: 'POST' });
  },

  deactivateUser: async (userId: string): Promise<void> => {
    await fetchApi(`/auth/users/${userId}/deactivate`, { method: 'POST' });
  },

  deleteUser: async (userId: string): Promise<void> => {
    await fetchApi(`/auth/users/${userId}`, { method: 'DELETE' });
  },

  changePassword: async (currentPassword: string, newPassword: string): Promise<void> => {
    await fetchApi('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },

  // Knowledge Graph
  getKnowledgeGraph: async (): Promise<{
    nodes: Array<{
      id: string;
      label: string;
      fullLabel: string;
      type: string;
      color: string;
      properties: Record<string, unknown>;
    }>;
    links: Array<{
      source: string;
      target: string;
      type: string;
      label: string;
    }>;
    stats: {
      total_nodes: number;
      total_links: number;
      node_types: Record<string, number>;
    };
  }> => {
    return fetchApi('/knowledge/graph');
  },

  clearKnowledgeGraph: async (): Promise<{ deleted_nodes: number }> => {
    return fetchApi('/knowledge/graph', { method: 'DELETE' });
  },

  // API Key Management
  getApiKeyStatus: async (): Promise<{
    has_api_key: boolean;
    message: string;
  }> => {
    return fetchApi('/auth/me/api-key/status');
  },

  setApiKey: async (apiKey: string): Promise<{
    has_api_key: boolean;
    message: string;
  }> => {
    return fetchApi('/auth/me/api-key', {
      method: 'PUT',
      body: JSON.stringify({ api_key: apiKey }),
    });
  },

  removeApiKey: async (): Promise<{
    has_api_key: boolean;
    message: string;
  }> => {
    return fetchApi('/auth/me/api-key', { method: 'DELETE' });
  },

  // Timezone Management
  getTimezone: async (): Promise<{
    timezone: string;
    message: string;
  }> => {
    return fetchApi('/auth/me/timezone');
  },

  setTimezone: async (timezone: string): Promise<{
    timezone: string;
    message: string;
  }> => {
    return fetchApi('/auth/me/timezone', {
      method: 'PUT',
      body: JSON.stringify({ timezone }),
    });
  },

  // Google Calendar
  getCalendarStatus: async (): Promise<{
    connected: boolean;
    email: string | null;
    calendar_enabled: boolean;
    selected_calendar_id: string | null;
    sync_confirmed_only: boolean;
  }> => {
    return fetchApi('/calendar/status');
  },

  connectCalendar: async (): Promise<{
    authorization_url: string;
  }> => {
    return fetchApi('/calendar/connect', { method: 'POST' });
  },

  disconnectCalendar: async (): Promise<void> => {
    await fetchApi('/calendar/disconnect', { method: 'POST' });
  },

  getCalendars: async (): Promise<Array<{
    id: string;
    name: string;
    is_primary: boolean;
  }>> => {
    return fetchApi('/calendar/calendars');
  },

  // Deep Research
  createResearch: async (question: string, depth: 1 | 2 | 3 = 1, persona?: string | null): Promise<ResearchListItem> => {
    return fetchApi<ResearchListItem>('/research', {
      method: 'POST',
      body: JSON.stringify({ question, depth, persona: persona && persona !== 'none' ? persona : undefined }),
    });
  },

  listResearch: async (): Promise<ResearchListItem[]> => {
    return fetchApi<ResearchListItem[]>('/research');
  },

  getResearch: async (id: string): Promise<ResearchDetail> => {
    return fetchApi<ResearchDetail>(`/research/${id}`);
  },

  deleteResearch: async (id: string): Promise<void> => {
    await fetchApi(`/research/${id}`, { method: 'DELETE' });
  },

  cancelResearch: async (id: string): Promise<ResearchListItem> => {
    return fetchApi<ResearchListItem>(`/research/${id}/cancel`, { method: 'POST' });
  },

  narrateResearch: async (id: string): Promise<{ status: string; bytes: number; voice: string }> => {
    return fetchApi(`/research/${id}/narrate`, { method: 'POST' });
  },

  /** <img>/<audio> can't send headers, so these carry the token as a query param. */
  researchFigureUrl: (id: string, ordinal: number): string => {
    const token = useAuthStore.getState().token ?? '';
    return `${API_BASE}/research/${id}/figures/${ordinal}?token=${encodeURIComponent(token)}`;
  },

  researchAudioUrl: (id: string): string => {
    const token = useAuthStore.getState().token ?? '';
    return `${API_BASE}/research/${id}/audio?token=${encodeURIComponent(token)}`;
  },

  // Evals (superuser)
  evals: {
    suites: () => fetchApi<EvalSuite[]>('/evals/suites'),
    runs: (suite?: string) => fetchApi<EvalRunItem[]>(`/evals/runs${suite ? `?suite=${encodeURIComponent(suite)}` : ''}`),
    run: (id: string) => fetchApi<EvalRunDetail>(`/evals/runs/${id}`),
    cases: (runId: string) => fetchApi<EvalCaseRow[]>(`/evals/runs/${runId}/cases`),
    caseResult: (id: string) => fetchApi<EvalCaseDetail>(`/evals/cases/${id}`),
    start: (body: { suite?: string; conversation_ids?: string[]; rubrics?: string[]; judge: string; repeats?: number; concurrency?: number; case_ids?: string[] }) =>
      fetchApi<{ id: string; status: string }>('/evals/runs', { method: 'POST', body: JSON.stringify(body) }),
    compare: (a: string, b: string) => fetchApi<RunComparison>(`/evals/compare?a=${a}&b=${b}`),
    graph: () => fetchApi<FsmTopology>('/evals/graph'),
    conversations: () => fetchApi<TracedConversation[]>('/evals/conversations'),
    conversationTraces: (id: string) => fetchApi<ConversationTrace[]>(`/evals/traces/conversation/${id}`),
  },

  updateCalendarSettings: async (settings: {
    calendar_enabled?: boolean;
    selected_calendar_id?: string | null;
    sync_confirmed_only?: boolean;
  }): Promise<void> => {
    await fetchApi('/calendar/settings', {
      method: 'PATCH',
      body: JSON.stringify(settings),
    });
  },
};

export { ApiError };

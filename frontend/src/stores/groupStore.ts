import { create } from 'zustand';
import type { Group, GroupDetail, GroupConversation, GroupConversationDetail, ExtractedEvent, SocialSuggestion } from '../types';
import { api } from '../lib/api';

interface GroupState {
  groups: Group[];
  selectedGroupId: string | null;
  selectedGroup: GroupDetail | null;
  conversations: GroupConversation[];
  selectedConversationId: string | null;
  selectedConversation: GroupConversationDetail | null;
  events: ExtractedEvent[];
  suggestions: SocialSuggestion[];
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchGroups: () => Promise<void>;
  selectGroup: (groupId: string | null) => Promise<void>;
  selectConversation: (conversationId: string | null) => Promise<void>;
  createGroup: (name: string, description?: string) => Promise<Group>;
  deleteGroup: (groupId: string) => Promise<void>;
  createConversation: (title?: string) => Promise<GroupConversation | null>;
  fetchEvents: () => Promise<void>;
  fetchSuggestions: () => Promise<void>;
  addEvent: (event: Partial<ExtractedEvent>) => void;
  clearSelection: () => void;
}

export const useGroupStore = create<GroupState>((set, get) => ({
  groups: [],
  selectedGroupId: null,
  selectedGroup: null,
  conversations: [],
  selectedConversationId: null,
  selectedConversation: null,
  events: [],
  suggestions: [],
  isLoading: false,
  error: null,

  fetchGroups: async () => {
    set({ isLoading: true, error: null });
    try {
      const groups = await api.listGroups();
      set({ groups, isLoading: false });
    } catch (error) {
      set({ error: 'Failed to load groups', isLoading: false });
      console.error('Failed to fetch groups:', error);
    }
  },

  selectGroup: async (groupId: string | null) => {
    if (!groupId) {
      set({ 
        selectedGroupId: null, 
        selectedGroup: null, 
        conversations: [],
        selectedConversationId: null,
        selectedConversation: null,
        events: [],
        suggestions: [],
      });
      return;
    }

    // IMPORTANT: Clear conversation selection IMMEDIATELY when changing groups
    // This prevents the WebSocket from trying to connect with an old conversation
    // that doesn't belong to the new group (which would cause 403 errors)
    set({ 
      selectedGroupId: groupId, 
      selectedConversationId: null,
      selectedConversation: null,
      isLoading: true, 
      error: null,
    });
    
    try {
      const [group, conversations] = await Promise.all([
        api.getGroup(groupId),
        api.listGroupConversations(groupId),
      ]);
      set({ 
        selectedGroup: group, 
        conversations, 
        isLoading: false,
      });

      // Also fetch events and suggestions in the background
      get().fetchEvents();
      get().fetchSuggestions();
    } catch (error) {
      set({ error: 'Failed to load group details', isLoading: false });
      console.error('Failed to select group:', error);
    }
  },

  selectConversation: async (conversationId: string | null) => {
    const { selectedGroupId } = get();
    if (!conversationId || !selectedGroupId) {
      set({ selectedConversationId: null, selectedConversation: null });
      return;
    }

    set({ selectedConversationId: conversationId, isLoading: true });
    try {
      const conversation = await api.getGroupConversation(selectedGroupId, conversationId);
      set({ selectedConversation: conversation, isLoading: false });
    } catch (error) {
      set({ error: 'Failed to load conversation', isLoading: false });
      console.error('Failed to select conversation:', error);
    }
  },

  createGroup: async (name: string, description?: string) => {
    const group = await api.createGroup(name, description);
    set((state) => ({ groups: [group, ...state.groups] }));
    return group;
  },

  deleteGroup: async (groupId: string) => {
    await api.deleteGroup(groupId);
    const { selectedGroupId } = get();
    set((state) => ({
      groups: state.groups.filter(g => g.id !== groupId),
      ...(selectedGroupId === groupId ? {
        selectedGroupId: null,
        selectedGroup: null,
        conversations: [],
        selectedConversationId: null,
        selectedConversation: null,
      } : {}),
    }));
  },

  createConversation: async (title?: string) => {
    const { selectedGroupId } = get();
    if (!selectedGroupId) return null;

    try {
      const conversation = await api.createGroupConversation(selectedGroupId, title);
      set((state) => ({ conversations: [conversation, ...state.conversations] }));
      return conversation;
    } catch (error) {
      console.error('Failed to create conversation:', error);
      return null;
    }
  },

  fetchEvents: async () => {
    const { selectedGroupId } = get();
    if (!selectedGroupId) return;

    try {
      const events = await api.listUpcomingEvents(selectedGroupId);
      set({ events });
    } catch (error) {
      console.error('Failed to fetch events:', error);
    }
  },

  fetchSuggestions: async () => {
    const { selectedGroupId } = get();
    if (!selectedGroupId) return;

    try {
      const suggestions = await api.getSocialSuggestions(selectedGroupId);
      set({ suggestions });
    } catch (error) {
      console.error('Failed to fetch suggestions:', error);
    }
  },

  addEvent: (event: Partial<ExtractedEvent>) => {
    // Add a new event from WebSocket notification
    if (event.id) {
      set((state) => ({
        events: [event as ExtractedEvent, ...state.events],
      }));
    }
  },

  clearSelection: () => {
    set({
      selectedGroupId: null,
      selectedGroup: null,
      conversations: [],
      selectedConversationId: null,
      selectedConversation: null,
      events: [],
      suggestions: [],
    });
  },
}));

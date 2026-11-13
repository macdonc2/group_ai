import { create } from 'zustand';
import { api } from '../lib/api';
import type { JournalEntry, JournalMessage } from '../types/journal';

interface JournalState {
  /** "Today" and the timezone as the server sees them for this user. */
  today: string | null;
  timezone: string;
  month: string | null;
  days: Record<string, number>;
  selectedDay: string | null;
  entries: JournalEntry[];
  messages: JournalMessage[];
  loadingDay: boolean;
  saving: boolean;
  sending: boolean;
  /** The reply being written, and what the agent is doing while it works. */
  streaming: string;
  activity: string | null;
  error: string | null;

  init: () => Promise<void>;
  showMonth: (month: string) => Promise<void>;
  selectDay: (day: string) => Promise<void>;
  addEntry: (body: string) => Promise<boolean>;
  updateEntry: (id: string, body: string) => Promise<boolean>;
  deleteEntry: (id: string) => Promise<void>;
  retryMemory: (id: string) => Promise<void>;
  answerSuggestion: (entryId: string, suggestionId: string, answer: 'accept' | 'dismiss') => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  clearChat: () => Promise<void>;
  dismissError: () => void;
}

function errorText(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : '';
  try {
    const detail = JSON.parse(raw).detail;
    if (typeof detail === 'string') return detail;
  } catch {
    // not JSON
  }
  return raw && raw.length < 200 ? raw : fallback;
}

const TOOL_LABELS: Record<string, string> = {
  read_journal: 'Reading your journal',
  recall_about_topic: 'Checking memory',
  list_entities: 'Checking memory',
  get_upcoming_events: 'Looking at your calendar',
  add_to_calendar: 'Adding to your calendar',
};

let watcher: ReturnType<typeof setTimeout> | null = null;

export const useJournalStore = create<JournalState>((set, get) => {
  const replaceEntry = (entry: JournalEntry) =>
    set((s) => ({ entries: s.entries.map((e) => (e.id === entry.id ? entry : e)) }));

  const refreshMonth = async () => {
    const month = get().month;
    if (!month) return;
    try {
      const data = await api.journalDays(month);
      if (get().month === month) set({ days: data.days, today: data.today, timezone: data.timezone });
    } catch {
      // the calendar marks are a convenience; the day view reports real failures
    }
  };

  // Memory and calendar suggestions are built after the save returns; poll until they settle.
  const watchMemory = (day: string, attempt = 0) => {
    if (watcher) clearTimeout(watcher);
    if (attempt > 40) return;
    watcher = setTimeout(async () => {
      if (get().selectedDay !== day) return;
      try {
        const entries = await api.journalEntries(day);
        if (get().selectedDay !== day) return;
        set({ entries });
        if (entries.some((e) => e.memory_status === 'pending')) watchMemory(day, attempt + 1);
      } catch {
        watchMemory(day, attempt + 1);
      }
    }, 1500);
  };

  return {
    today: null,
    timezone: 'UTC',
    month: null,
    days: {},
    selectedDay: null,
    entries: [],
    messages: [],
    loadingDay: false,
    saving: false,
    sending: false,
    streaming: '',
    activity: null,
    error: null,

    init: async () => {
      try {
        const data = await api.journalDays(get().month ?? undefined);
        set({ today: data.today, timezone: data.timezone, month: data.month, days: data.days });
        if (!get().selectedDay) await get().selectDay(data.today);
      } catch (error) {
        set({ error: errorText(error, 'Could not load your journal.') });
      }
    },

    showMonth: async (month) => {
      set({ month, days: {} });
      await refreshMonth();
    },

    selectDay: async (day) => {
      if (get().sending) return; // a reply in progress belongs to the open day
      set({ selectedDay: day, entries: [], messages: [], loadingDay: true, error: null, streaming: '', activity: null });
      try {
        const [entries, messages] = await Promise.all([api.journalEntries(day), api.journalChat(day)]);
        if (get().selectedDay !== day) return;
        set({ entries, messages, loadingDay: false });
        if (entries.some((e) => e.memory_status === 'pending')) watchMemory(day);
      } catch (error) {
        if (get().selectedDay === day) set({ loadingDay: false, error: errorText(error, 'Could not load that day.') });
      }
    },

    addEntry: async (body) => {
      const day = get().selectedDay;
      if (!day || !body.trim()) return false;
      set({ saving: true, error: null });
      try {
        const entry = await api.createJournalEntry(body, day);
        if (get().selectedDay === day) {
          set((s) => ({ entries: [...s.entries, entry] }));
          watchMemory(day);
        }
        set((s) => ({ saving: false, days: { ...s.days, [day]: (s.days[day] ?? 0) + 1 } }));
        return true;
      } catch (error) {
        set({ saving: false, error: errorText(error, 'Could not save the entry. Your text is still in the box.') });
        return false;
      }
    },

    updateEntry: async (id, body) => {
      const day = get().selectedDay;
      set({ error: null });
      try {
        replaceEntry(await api.updateJournalEntry(id, body));
        if (day) watchMemory(day);
        return true;
      } catch (error) {
        set({ error: errorText(error, 'Could not save the change.') });
        return false;
      }
    },

    deleteEntry: async (id) => {
      set({ error: null });
      try {
        await api.deleteJournalEntry(id);
        set((s) => ({ entries: s.entries.filter((e) => e.id !== id) }));
        await refreshMonth();
      } catch (error) {
        set({ error: errorText(error, 'Could not delete the entry.') });
      }
    },

    retryMemory: async (id) => {
      const day = get().selectedDay;
      try {
        replaceEntry(await api.retryJournalMemory(id));
        if (day) watchMemory(day);
      } catch (error) {
        set({ error: errorText(error, 'Could not retry.') });
      }
    },

    answerSuggestion: async (entryId, suggestionId, answer) => {
      set({ error: null });
      try {
        replaceEntry(await api.answerJournalSuggestion(entryId, suggestionId, answer));
      } catch (error) {
        set({ error: errorText(error, 'Could not add that to your calendar.') });
      }
    },

    sendMessage: async (text) => {
      const day = get().selectedDay;
      const message = text.trim();
      if (!day || !message || get().sending) return;
      const mine: JournalMessage = {
        id: `local-${Date.now()}`, role: 'user', content: message, tools_used: [], created_at: new Date().toISOString(),
      };
      set((s) => ({ messages: [...s.messages, mine], sending: true, streaming: '', activity: 'Thinking', error: null }));
      let reply: JournalMessage | null = null;
      let failure: string | null = null;
      try {
        await api.streamJournalChat(day, message, (event) => {
          if (event.event_type === 'response_chunk') {
            set((s) => ({ streaming: s.streaming + event.message, activity: null }));
          } else if (event.event_type === 'tool_result') {
            const tool = String(event.data?.tool_name ?? '');
            set({ activity: TOOL_LABELS[tool] ?? 'Working', streaming: '' });
          } else if (event.event_type === 'response') {
            reply = {
              id: String(event.data?.message_id ?? `local-${Date.now()}-a`),
              role: 'assistant',
              content: String(event.data?.response ?? ''),
              tools_used: (event.data?.tools_used as string[] | undefined) ?? [],
              created_at: new Date().toISOString(),
            };
          } else if (event.event_type === 'error') {
            failure = event.message;
          }
        });
      } catch (error) {
        failure = errorText(error, 'The connection was lost. Please try again.');
      }
      const finished = reply as JournalMessage | null;
      set((s) => ({
        sending: false,
        streaming: '',
        activity: null,
        messages: finished && s.selectedDay === day ? [...s.messages, finished] : s.messages,
        error: finished ? null : failure ?? 'No reply came back. Please try again.',
      }));
      // The agent may have added a calendar event or nothing at all; entries are unchanged either way.
    },

    clearChat: async () => {
      const day = get().selectedDay;
      if (!day || get().sending) return;
      try {
        await api.clearJournalChat(day);
        if (get().selectedDay === day) set({ messages: [] });
      } catch (error) {
        set({ error: errorText(error, 'Could not clear the conversation.') });
      }
    },

    dismissError: () => set({ error: null }),
  };
});

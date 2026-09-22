import { create } from 'zustand';
import { api } from '../lib/api';
import type {
  ConversationTrace,
  EvalCaseDetail,
  EvalCaseRow,
  EvalRunDetail,
  EvalRunItem,
  EvalSuite,
  FsmTopology,
  TracedConversation,
} from '../types';

export type EvalSidebarMode = 'runs' | 'conversations';

interface EvalState {
  mode: EvalSidebarMode;
  suites: EvalSuite[];
  runs: EvalRunItem[];
  topology: FsmTopology | null;
  selectedRunId: string | null;
  run: EvalRunDetail | null;
  cases: EvalCaseRow[];
  selectedCaseId: string | null;
  caseDetail: EvalCaseDetail | null;
  conversations: TracedConversation[];
  selectedConversationId: string | null;
  conversationTraces: ConversationTrace[];
  compareWith: string | null;
  evalSelection: string[]; // conversation ids ticked for a conversation eval
  loading: boolean;
  error: string | null;

  setMode: (mode: EvalSidebarMode) => void;
  loadIndex: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  selectRun: (id: string | null) => Promise<void>;
  selectCase: (id: string | null) => Promise<void>;
  selectConversation: (id: string | null) => Promise<void>;
  startRun: (body: { suite?: string; conversation_ids?: string[]; judge: string; repeats?: number; case_ids?: string[] }) => Promise<string | null>;
  setCompareWith: (id: string | null) => void;
  toggleEvalSelection: (id: string) => void;
  setEvalSelection: (ids: string[]) => void;
  evaluateSelected: (judge: string) => Promise<void>;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const useEvalStore = create<EvalState>()((set, get) => ({
  mode: 'runs',
  suites: [],
  runs: [],
  topology: null,
  selectedRunId: null,
  run: null,
  cases: [],
  selectedCaseId: null,
  caseDetail: null,
  conversations: [],
  selectedConversationId: null,
  conversationTraces: [],
  compareWith: null,
  evalSelection: [],
  loading: false,
  error: null,

  setMode: (mode) => {
    set({ mode });
    if (mode === 'conversations' && get().conversations.length === 0) {
      api.evals.conversations().then((conversations) => set({ conversations })).catch((e) => set({ error: message(e) }));
    }
  },

  loadIndex: async () => {
    try {
      const [suites, runs, topology] = await Promise.all([api.evals.suites(), api.evals.runs(), api.evals.graph()]);
      set({ suites, runs, topology, error: null });
    } catch (e) {
      set({ error: message(e) });
    }
  },

  refreshRuns: async () => {
    try {
      const runs = await api.evals.runs();
      set({ runs });
      const { selectedRunId } = get();
      if (selectedRunId && runs.some((r) => r.id === selectedRunId)) {
        const [run, cases] = await Promise.all([api.evals.run(selectedRunId), api.evals.cases(selectedRunId)]);
        set({ run, cases });
      }
    } catch (e) {
      set({ error: message(e) });
    }
  },

  selectRun: async (id) => {
    set({ selectedRunId: id, run: null, cases: [], selectedCaseId: null, caseDetail: null, compareWith: null });
    if (!id) return;
    set({ loading: true });
    try {
      const [run, cases] = await Promise.all([api.evals.run(id), api.evals.cases(id)]);
      if (get().selectedRunId === id) set({ run, cases, error: null });
    } catch (e) {
      set({ error: message(e) });
    } finally {
      set({ loading: false });
    }
  },

  selectCase: async (id) => {
    set({ selectedCaseId: id, caseDetail: null });
    if (!id) return;
    try {
      const caseDetail = await api.evals.caseResult(id);
      if (get().selectedCaseId === id) set({ caseDetail });
    } catch (e) {
      set({ error: message(e) });
    }
  },

  selectConversation: async (id) => {
    set({ selectedConversationId: id, conversationTraces: [] });
    if (!id) return;
    try {
      const conversationTraces = await api.evals.conversationTraces(id);
      if (get().selectedConversationId === id) set({ conversationTraces });
    } catch (e) {
      set({ error: message(e) });
    }
  },

  startRun: async (body) => {
    try {
      const { id } = await api.evals.start(body);
      await get().refreshRuns();
      await get().selectRun(id);
      return id;
    } catch (e) {
      set({ error: message(e) });
      return null;
    }
  },

  setCompareWith: (id) => set({ compareWith: id }),

  toggleEvalSelection: (id) => {
    const cur = get().evalSelection;
    set({ evalSelection: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] });
  },

  setEvalSelection: (ids) => set({ evalSelection: ids }),

  evaluateSelected: async (judge) => {
    const ids = get().evalSelection;
    if (!ids.length) return;
    const runId = await get().startRun({ conversation_ids: ids, judge });
    if (runId) set({ mode: 'runs', evalSelection: [] });
  },
}));

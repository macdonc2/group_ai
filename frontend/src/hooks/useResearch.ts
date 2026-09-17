import { useCallback, useEffect, useRef } from 'react';
import { api } from '../lib/api';
import { createGenericSSE } from '../lib/sse';
import { TERMINAL_EVENTS, useResearchStore } from '../stores/researchStore';
import { useThemeStore } from '../stores/themeStore';
import type { ResearchStreamEvent } from '../types';

const LIVE_STATUSES = ['queued', 'running', 'synthesizing', 'writing', 'narrating'];

/**
 * Drives the Research tab: list, select, start, and (re)attach to the live
 * stream. Attaching replays the persisted history first, so a reload or a
 * tab switch mid-run picks up exactly where the job is.
 */
export function useResearch() {
  const store = useResearchStore();
  const abortRef = useRef<{ abort: () => void } | null>(null);
  const attachedRef = useRef<string | null>(null);

  const refreshList = useCallback(async () => {
    try {
      store.setJobs(await api.listResearch());
    } catch (e) {
      console.error('Failed to list research:', e);
    }
  }, [store.setJobs]); // eslint-disable-line react-hooks/exhaustive-deps

  const detach = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    attachedRef.current = null;
    useResearchStore.getState().setStreaming(false);
  }, []);

  const attach = useCallback((id: string) => {
    if (attachedRef.current === id) return;
    abortRef.current?.abort();
    attachedRef.current = id;
    useResearchStore.getState().setStreaming(true);
    abortRef.current = createGenericSSE<ResearchStreamEvent>(`/api/v1/research/${id}/stream`, {}, {
      terminalEvents: TERMINAL_EVENTS,
      onEvent: (event) => useResearchStore.getState().handleEvent(event),
      onError: () => {
        useResearchStore.getState().setStreaming(false);
      },
      onComplete: async () => {
        attachedRef.current = null;
        useResearchStore.getState().setStreaming(false);
        // Pull the final persisted state (figures list, audio flag, title).
        try {
          const detail = await api.getResearch(id);
          const st = useResearchStore.getState();
          if (st.selectedJobId === id) {
            st.setDetail(detail);
          }
          st.upsertJob(detail);
        } catch (e) {
          console.error('Failed to refresh research detail:', e);
        }
      },
    });
  }, []);

  const open = useCallback(async (id: string) => {
    const st = useResearchStore.getState();
    if (st.selectedJobId !== id) detach();
    st.select(id);
    try {
      const detail = await api.getResearch(id);
      st.setDetail(detail);
      if (LIVE_STATUSES.includes(detail.status)) {
        // The stream replays the whole history, which rebuilds counters, figures,
        // sources and the draft from scratch; start from zero so nothing is counted twice.
        st.resetLive();
        attach(id);
      }
    } catch (e) {
      console.error('Failed to load research:', e);
      st.setError('Could not load this research run.');
    }
  }, [attach, detach]);

  const start = useCallback(async (question: string, depth: 1 | 2 | 3 = 1) => {
    detach();
    const st = useResearchStore.getState();
    st.resetLive();
    st.setError(null);
    try {
      const job = await api.createResearch(question, depth, useThemeStore.getState().wrestler);
      st.upsertJob(job);
      st.select(job.id);
      st.setDetail({
        ...job, tldr: null, report_markdown: null, model: '', sources: [], figure_list: [],
        progress: { phase: 'queued', depth, figures: 0, has_audio: false, lanes: {
          academic: { status: 'pending', step: '', queries: 0, sources: 0, findings: 0, tables: 0, error: null },
          practical: { status: 'pending', step: '', queries: 0, sources: 0, findings: 0, tables: 0, error: null },
          empirical: { status: 'pending', step: '', queries: 0, sources: 0, findings: 0, tables: 0, error: null },
        } },
      });
      attach(job.id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      st.setError(msg.includes('API key') ? 'No OpenAI API key on file. Add one under API Key Settings.' : `Could not start research: ${msg}`);
    }
  }, [attach, detach]);

  const remove = useCallback(async (id: string) => {
    if (!window.confirm('Delete this research run and its report? This cannot be undone.')) return;
    try {
      await api.deleteResearch(id);
      if (useResearchStore.getState().selectedJobId === id) detach();
      useResearchStore.getState().removeJob(id);
    } catch (e) {
      console.error('Failed to delete research:', e);
    }
  }, [detach]);

  const startNew = useCallback(() => {
    detach();
    const st = useResearchStore.getState();
    st.select(null);
    st.setDetail(null);
    st.resetLive();
  }, [detach]);

  // On mount: load the list, and reopen the persisted selection.
  useEffect(() => {
    refreshList();
    const id = useResearchStore.getState().selectedJobId;
    if (id) open(id);
    return () => detach();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { refreshList, open, start, remove, startNew, detach };
}

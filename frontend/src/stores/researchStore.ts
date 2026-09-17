import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  LaneName,
  LaneProgress,
  ResearchDetail,
  ResearchFigure,
  ResearchListItem,
  ResearchSource,
  ResearchStreamEvent,
} from '../types';

export const LANES: LaneName[] = ['academic', 'practical', 'empirical'];

export const TERMINAL_EVENTS = ['job_complete', 'job_failed', 'job_interrupted'];

export interface LaneLog {
  time: number;
  kind: 'step' | 'query' | 'source' | 'finding' | 'table' | 'error' | 'done' | 'round' | 'gap';
  text: string;
}

export interface LaneView extends LaneProgress {
  log: LaneLog[];
  queryList: string[];
  round: number;
}

export interface PipelineStep {
  key: 'synthesis' | 'figures' | 'writer' | 'narration';
  label: string;
  status: 'pending' | 'running' | 'complete' | 'error';
  detail: string;
}

interface ResearchState {
  jobs: ResearchListItem[];
  selectedJobId: string | null;
  detail: ResearchDetail | null;
  lanes: Record<LaneName, LaneView>;
  pipeline: PipelineStep[];
  draft: string;             // streamed markdown while writing
  figures: ResearchFigure[];
  sources: ResearchSource[];
  isStreaming: boolean;
  error: string | null;

  setJobs: (jobs: ResearchListItem[]) => void;
  upsertJob: (job: ResearchListItem) => void;
  removeJob: (id: string) => void;
  select: (id: string | null) => void;
  setDetail: (detail: ResearchDetail | null) => void;
  resetLive: () => void;
  setStreaming: (v: boolean) => void;
  setError: (e: string | null) => void;
  handleEvent: (event: ResearchStreamEvent) => void;
}

const freshLane = (): LaneView => ({
  status: 'pending', step: '', queries: 0, sources: 0, findings: 0, tables: 0, error: null,
  log: [], queryList: [], round: 1,
});

const freshLanes = (): Record<LaneName, LaneView> => ({
  academic: freshLane(), practical: freshLane(), empirical: freshLane(),
});

const freshPipeline = (): PipelineStep[] => [
  { key: 'synthesis', label: 'Synthesis', status: 'pending', detail: '' },
  { key: 'figures', label: 'Figures', status: 'pending', detail: '' },
  { key: 'writer', label: 'Writing', status: 'pending', detail: '' },
  { key: 'narration', label: 'Narration', status: 'pending', detail: '' },
];

/** Rebuild the live lane view from a persisted progress snapshot (late joiners). */
export function lanesFromProgress(progress: ResearchDetail['progress'] | undefined): Record<LaneName, LaneView> {
  const lanes = freshLanes();
  if (!progress?.lanes) return lanes;
  for (const lane of LANES) {
    const p = progress.lanes[lane];
    if (p) lanes[lane] = { ...lanes[lane], ...p };
  }
  return lanes;
}

export function pipelineFromDetail(detail: ResearchDetail | null): PipelineStep[] {
  const p = freshPipeline();
  if (!detail) return p;
  const done = (k: PipelineStep['key'], detailText = '') => {
    const s = p.find((x) => x.key === k)!;
    s.status = 'complete';
    s.detail = detailText;
  };
  const phase = detail.progress?.phase ?? detail.phase;
  const order = ['synthesizing', 'writing', 'narrating', 'complete'];
  const idx = order.indexOf(phase);
  if (detail.title) done('synthesis', detail.title);
  if (detail.figures > 0 || idx >= 1) done('figures', `${detail.figures} figure${detail.figures === 1 ? '' : 's'}`);
  if (detail.report_markdown) done('writer', 'Report ready');
  if (detail.has_audio) done('narration', 'Narration ready');
  if (phase === 'synthesizing') p[0].status = 'running';
  if (phase === 'writing') p[2].status = 'running';
  if (phase === 'narrating') p[3].status = 'running';
  return p;
}

export const useResearchStore = create<ResearchState>()(
  persist(
    (set, get) => ({
      jobs: [],
      selectedJobId: null,
      detail: null,
      lanes: freshLanes(),
      pipeline: freshPipeline(),
      draft: '',
      figures: [],
      sources: [],
      isStreaming: false,
      error: null,

      setJobs: (jobs) => set({ jobs }),
      upsertJob: (job) => set((s) => ({
        jobs: s.jobs.some((j) => j.id === job.id)
          ? s.jobs.map((j) => (j.id === job.id ? job : j))
          : [job, ...s.jobs],
      })),
      removeJob: (id) => set((s) => ({
        jobs: s.jobs.filter((j) => j.id !== id),
        selectedJobId: s.selectedJobId === id ? null : s.selectedJobId,
        detail: s.selectedJobId === id ? null : s.detail,
      })),
      select: (id) => set({ selectedJobId: id }),
      setDetail: (detail) => set({
        detail,
        lanes: lanesFromProgress(detail?.progress),
        pipeline: pipelineFromDetail(detail),
        figures: detail?.figure_list ?? [],
        sources: detail?.sources ?? [],
        draft: detail?.report_markdown ?? '',
        error: detail?.error ?? null,
      }),
      resetLive: () => set({
        lanes: freshLanes(), pipeline: freshPipeline(), draft: '', figures: [], sources: [], error: null,
      }),
      setStreaming: (isStreaming) => set({ isStreaming }),
      setError: (error) => set({ error }),

      handleEvent: (event) => {
        const { event_type: type, node_name: node, message, data } = event;
        const s = get();
        // Keep the sidebar's status pill in step with the stream.
        const statusFor: Record<string, ResearchListItem['status'] | undefined> = {
          job_start: 'running', synthesis_start: 'synthesizing', writing_start: 'writing',
          narration_start: 'narrating', job_complete: 'complete', job_failed: 'failed', job_interrupted: 'interrupted',
        };
        const nextStatus = statusFor[type];
        if (nextStatus && s.selectedJobId) {
          const phase = nextStatus === 'complete' ? 'complete' : nextStatus === 'running' ? 'running' : nextStatus;
          set({
            jobs: s.jobs.map((j) => (j.id === s.selectedJobId ? { ...j, status: nextStatus, phase } : j)),
            detail: s.detail && s.detail.id === s.selectedJobId ? { ...s.detail, status: nextStatus, phase } : s.detail,
          });
        }
        const lanes = { ...s.lanes };
        const pipeline = s.pipeline.map((p) => ({ ...p }));
        const now = event.timestamp || Date.now() / 1000;
        const setStep = (key: PipelineStep['key'], status: PipelineStep['status'], detail?: string) => {
          const step = pipeline.find((p) => p.key === key)!;
          step.status = status;
          if (detail !== undefined) step.detail = detail;
        };

        if (node && LANES.includes(node as LaneName)) {
          const lane = { ...lanes[node as LaneName], log: [...lanes[node as LaneName].log] };
          switch (type) {
            case 'lane_start':
              lane.status = 'running';
              break;
            case 'lane_step':
              lane.step = message;
              lane.log.push({ time: now, kind: 'step', text: message });
              break;
            case 'lane_round':
              lane.round = (data?.round as number) ?? lane.round + 1;
              lane.log.push({ time: now, kind: 'round', text: `Round ${lane.round}: reviewing findings and gaps` });
              break;
            case 'lane_gaps':
              ((data?.gaps as string[]) ?? []).forEach((g) => lane.log.push({ time: now, kind: 'gap', text: g }));
              break;
            case 'lane_queries': {
              const qs = (data?.queries as string[]) ?? [];
              lane.queryList = [...lane.queryList, ...qs];
              lane.queries += qs.length;
              qs.forEach((q) => lane.log.push({ time: now, kind: 'query', text: q }));
              break;
            }
            case 'lane_sources': {
              const found = (data?.sources as ResearchSource[]) ?? [];
              lane.sources += found.length;
              found.forEach((src) => lane.log.push({ time: now, kind: 'source', text: src.title }));
              break;
            }
            case 'lane_finding':
              lane.findings += 1;
              lane.log.push({ time: now, kind: 'finding', text: message });
              break;
            case 'lane_tables':
              lane.tables = ((data?.tables as unknown[]) ?? []).length;
              lane.log.push({ time: now, kind: 'table', text: message });
              break;
            case 'lane_complete':
              lane.status = 'complete';
              lane.step = 'done';
              lane.log.push({ time: now, kind: 'done', text: message });
              break;
            case 'lane_error':
              lane.status = 'error';
              lane.error = (data?.error as string) ?? message;
              lane.log.push({ time: now, kind: 'error', text: message });
              break;
          }
          lanes[node as LaneName] = lane;
          set({ lanes });
          return;
        }

        switch (type) {
          case 'synthesis_start':
            setStep('synthesis', 'running', message);
            set({ pipeline });
            break;
          case 'synthesis_complete':
            setStep('synthesis', 'complete', (data?.title as string) ?? message);
            set({ pipeline, sources: (data?.sources as ResearchSource[]) ?? s.sources });
            break;
          case 'figure_rendered': {
            const fig: ResearchFigure = {
              ordinal: data?.ordinal as number,
              caption: (data?.caption as string) ?? message,
              source_ids: [],
              origin: ((data?.origin as string) === 'source' ? 'source' : 'generated'),
              source_url: (data?.source_url as string | null) ?? null,
              source_title: (data?.source_title as string | null) ?? null,
            };
            const figures = [...s.figures.filter((f) => f.ordinal !== fig.ordinal), fig].sort((a, b) => a.ordinal - b.ordinal);
            setStep('figures', 'complete', `${figures.length} figure${figures.length === 1 ? '' : 's'}`);
            set({ pipeline, figures });
            break;
          }
          case 'figures_start':
            setStep('figures', 'running', message);
            set({ pipeline });
            break;
          case 'figure_skipped':
            setStep('figures', 'complete', message);
            set({ pipeline });
            break;
          case 'writing_start':
            if (pipeline[1].status === 'pending') setStep('figures', 'complete', 'No figures');
            setStep('writer', 'running', 'Writing…');
            set({ pipeline, draft: '' });
            break;
          case 'writing_chunk':
            set({ draft: s.draft + message });
            break;
          case 'report_complete':
            setStep('writer', 'complete', 'Report ready');
            set({
              pipeline,
              draft: (data?.markdown as string) ?? s.draft,
              figures: (data?.figures as ResearchFigure[]) ?? s.figures,
            });
            break;
          case 'narration_start':
            setStep('narration', 'running', message);
            set({ pipeline });
            break;
          case 'narration_complete':
            setStep('narration', 'complete', 'Narration ready');
            set({ pipeline, detail: s.detail ? { ...s.detail, has_audio: true } : s.detail });
            break;
          case 'narration_failed':
            setStep('narration', 'error', message);
            set({ pipeline });
            break;
          case 'job_complete':
            set({ isStreaming: false });
            break;
          case 'job_failed':
          case 'job_interrupted':
            set({ isStreaming: false, error: message });
            break;
        }
      },
    }),
    {
      name: 'research-storage',
      partialize: (state) => ({ selectedJobId: state.selectedJobId }),
    }
  )
);

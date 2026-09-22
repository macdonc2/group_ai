// Types for the Evals tab. Mirrors agent_system/adapters/inbound/api/routes/evals.py
// and the TurnTrace.to_dict() shape in adapters/outbound/telemetry/trace.py.

export interface TraceSpan {
  node: string;
  seq: number;
  start_ms: number;
  end_ms: number | null;
  duration_ms: number | null;
  input_tokens?: number;
  output_tokens?: number;
  llm_ms?: number;
  cost_usd?: number;
}

export interface TraceDecision {
  t_ms: number;
  seq: number | null;
  node: string;
  predicate: string;
  result: boolean;
  next: string;
  inputs: Record<string, unknown>;
}

export interface TraceEvent {
  t_ms: number;
  seq: number | null;
  type: string;
  node: string;
  message: string;
  data: Record<string, unknown>;
}

export interface RetrievalHit {
  id?: string;
  name?: string;
  type?: string;
  role?: string;
  score?: number | null;
  content?: string;
  used_in_prompt?: boolean;
}

export interface TraceRetrieval {
  t_ms: number;
  seq: number | null;
  node: string | null;
  source: string;
  query: string;
  params: Record<string, unknown>;
  hits: RetrievalHit[];
}

export interface TraceToolCall {
  t_ms: number;
  seq: number | null;
  tool: string;
  arguments: Record<string, unknown>;
  result: string | null;
  success: boolean;
  duration_ms: number;
}

export interface TraceLLMCall {
  node: string | null;
  agent: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  duration_ms: number;
  cost_usd: number | null;
  at_ms: number;
  input_preview: string | null;
  output_preview: string | null;
  role: 'system' | 'judge';
}

export interface Usage {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  embedding_tokens: number;
  cost_usd: number | null;
  unpriced_calls: number;
}

export interface TurnTrace {
  version: number;
  user_input: string;
  started_at?: number;
  total_ms: number | null;
  path: string[];
  spans: TraceSpan[];
  decisions: TraceDecision[];
  events: TraceEvent[];
  retrievals: TraceRetrieval[];
  tool_calls: TraceToolCall[];
  llm_calls: TraceLLMCall[];
  embedding_calls: { node: string | null; model: string; tokens: number; duration_ms: number; cost_usd: number | null }[];
  usage: Usage;
  response: string | null;
  error: string | null;
}

export interface FsmTopology {
  start: string;
  nodes: { id: string; doc: string }[];
  edges: { source: string; target: string; label: string | null }[];
}

export interface EvalSuite {
  name: string;
  kind: 'agent' | 'research';
  description: string;
  rubrics: string[];
  cases: string[];
}

export interface EvalRunItem {
  id: string;
  suite: string;
  status: 'running' | 'complete' | 'failed' | 'interrupted';
  judge: string;
  git_sha: string | null;
  started_at: string | null;
  completed_at: string | null;
  pass_rate: number | null;
  cases: number | null;
  passed: number | null;
  cost_usd: number | null;
  p50_ms: number | null;
  total: number | null;
  done: number | null;
  live: boolean;
}

export interface EvalSummary {
  cases: number;
  passed: number;
  pass_rate: number | null;
  deterministic: Record<string, number>;
  judge: Record<string, Record<string, number>>;
  agreement: { judges: string[]; n: number; exact: number | null; within_1: number | null; weighted_kappa: number | null } | null;
  latency: {
    turn_p50_ms: number | null;
    turn_p95_ms: number | null;
    by_node: Record<string, { p50: number | null; p95: number | null; n: number }>;
  };
  cost: {
    system_usd: number | null;
    per_case_usd: number | null;
    judge_usd: number | null;
    unpriced_cases: number;
    unpriced_calls?: number;
    judge_unpriced_calls?: number;
    tokens: { input: number; output: number };
  };
  failure_counts: Record<string, number>;
  flag_counts?: Record<string, number>;
}

export interface EvalRunDetail extends EvalRunItem {
  config: Record<string, unknown>;
  summary: EvalSummary | Record<string, never>;
  failure_analysis_md: string | null;
  error: string | null;
}

export interface EvalCaseRow {
  id: string;
  case_id: string;
  repeat: number;
  passed: boolean;
  failure_tags: string[];
  description: string;
  user: string | null;
  scores: Record<string, { score: number; passed: boolean }>;
  judge_means: Record<string, number | null>;
  total_ms: number | null;
  cost_usd: number | null;
  error: string | null;
}

export interface ScoreDetail {
  name: string;
  score: number;
  passed: boolean;
  tag: string;
  detail: Record<string, unknown>;
}

export interface RubricJudgement {
  dimensions?: Record<string, { score: number | null; rationale: string }>;
  mean?: number | null;
  summary?: string;
  error?: string;
}

export interface EvalTurn {
  user: string;
  response: string;
  trace?: TurnTrace;
  research?: { sources: Record<string, unknown>[]; usage: Record<string, unknown>; status: string; lanes_with_findings: string[] };
}

export interface EvalCaseDetail {
  id: string;
  run_id: string;
  case_id: string;
  repeat: number;
  passed: boolean;
  failure_tags: string[];
  case: {
    id: string;
    description?: string;
    seed?: Record<string, unknown[] | boolean>;
    turns?: string[];
    expect?: { route?: string[] | null; forbid_nodes?: string[]; answer_criteria?: string | null } & Record<string, unknown>;
    question?: string;
  };
  scores: Record<string, ScoreDetail>;
  judgements: Record<string, Record<string, RubricJudgement>>;
  entity_snapshot: Record<string, Record<string, unknown>[]> | null;
  turns: EvalTurn[];
  total_ms: number | null;
  cost_usd: number | null;
  judge_cost_usd: number | null;
  error: string | null;
}

export interface TracedConversation {
  conversation_id: string;
  title: string | null;
  messages: number;
  traced_turns: number;
  last_at: string;
}

/** One turn of a real conversation; `trace` is null for turns from before tracing. */
export interface ConversationTrace {
  user: string;
  response: string | null;
  trace: TurnTrace | null;
  created_at: string | null;
}

export interface RunComparison {
  a: EvalRunItem;
  b: EvalRunItem;
  metrics: { metric: string; a: number | null; b: number | null; delta: number | null }[];
  regressions: string[];
  fixes: string[];
}

// Turns a TurnTrace + the static FSM topology into a predicate tree:
// the spine is the sequence of node visits (ReAct loops unroll into repeated
// visits); each visit hangs its untaken outgoing branches as ghost leaves; each
// edge carries the predicate that decided it.
import dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';
import type { FsmTopology, TraceDecision, TraceSpan, TurnTrace } from '../../types';

export type VisitStatus = 'expected' | 'forbidden' | 'neutral';

export interface VisitData extends Record<string, unknown> {
  kind: 'visit';
  name: string;
  span: TraceSpan;
  decisions: TraceDecision[];
  llmCalls: number;
  tokens: number;
  tools: string[];
  retrievals: number;
  status: VisitStatus;
  selected: boolean;
}

export interface GhostData extends Record<string, unknown> {
  kind: 'ghost';
  name: string;
  missed: boolean; // an expected node the run never reached
  label: string | null; // the static edge label, shown inside the leaf to keep edges uncluttered
}

export interface EndData extends Record<string, unknown> {
  kind: 'end';
  error: string | null;
}

export type TreeNodeData = VisitData | GhostData | EndData;

const VISIT_W = 236;
const GHOST_W = 150;

function visitHeight(d: VisitData) {
  return 58 + Math.min(d.decisions.length, 4) * 18;
}

export function buildTree(
  trace: TurnTrace,
  topology: FsmTopology | null,
  expect?: { route?: string[] | null; forbid_nodes?: string[] } | null,
  selectedSeq?: number | null,
): { nodes: Node<TreeNodeData>[]; edges: Edge[] } {
  const spans = [...trace.spans].sort((a, b) => a.seq - b.seq);
  const visited = new Set(spans.map((s) => s.node));
  const expected = new Set(expect?.route ?? []);
  const forbidden = new Set(expect?.forbid_nodes ?? []);
  const staticOut = new Map<string, { target: string; label: string | null }[]>();
  for (const e of topology?.edges ?? []) {
    staticOut.set(e.source, [...(staticOut.get(e.source) ?? []), { target: e.target, label: e.label }]);
  }

  const nodes: Node<TreeNodeData>[] = [];
  const edges: Edge[] = [];

  spans.forEach((span, i) => {
    const decisions = trace.decisions.filter((d) => d.seq === span.seq);
    const inSpan = (t: number) => t >= span.start_ms && (span.end_ms == null || t <= span.end_ms + 1);
    const llm = trace.llm_calls.filter((c) => c.role === 'system' && c.node === span.node && inSpan(c.at_ms));
    const data: VisitData = {
      kind: 'visit',
      name: span.node,
      span,
      decisions,
      llmCalls: llm.length,
      tokens: llm.reduce((n, c) => n + c.input_tokens + c.output_tokens, 0),
      tools: trace.tool_calls.filter((t) => t.seq === span.seq).map((t) => t.tool),
      retrievals: trace.retrievals.filter((r) => r.seq === span.seq).reduce((n, r) => n + r.hits.length, 0),
      status: forbidden.has(span.node) ? 'forbidden' : expected.has(span.node) ? 'expected' : 'neutral',
      selected: selectedSeq === span.seq,
    };
    const id = `v${span.seq}`;
    nodes.push({ id, type: 'visit', position: { x: 0, y: 0 }, data, width: VISIT_W, height: visitHeight(data) });

    const next = spans[i + 1];
    const outs = staticOut.get(span.node) ?? [];
    if (next) {
      const decided = [...decisions].reverse().find((d) => d.next === next.node);
      const staticLabel = outs.find((o) => o.target === next.node)?.label;
      edges.push({
        id: `e${span.seq}`,
        source: id,
        target: `v${next.seq}`,
        label: decided ? `${decided.predicate} = ${decided.result ? 'T' : 'F'}` : staticLabel ?? undefined,
        data: { decision: decided ?? null },
        className: 'pt-edge-taken',
        animated: false,
      });
    }
    // untaken branches
    for (const o of outs) {
      if (next && o.target === next.node) continue;
      if (!next && o.target === 'End') continue;
      const gid = `g${span.seq}-${o.target}`;
      const missed = expected.has(o.target) && !visited.has(o.target);
      nodes.push({
        id: gid, type: 'ghost', position: { x: 0, y: 0 },
        data: { kind: 'ghost', name: o.target, missed, label: o.label }, width: GHOST_W, height: o.label ? 44 : 34,
      });
      edges.push({
        id: `eg${span.seq}-${o.target}`,
        source: id,
        target: gid,
        className: missed ? 'pt-edge-missed' : 'pt-edge-ghost',
      });
    }
  });

  if (spans.length) {
    const last = spans[spans.length - 1];
    nodes.push({
      id: 'end', type: 'end', position: { x: 0, y: 0 },
      data: { kind: 'end', error: trace.error }, width: 110, height: 34,
    });
    edges.push({ id: 'e-end', source: `v${last.seq}`, target: 'end', className: trace.error ? 'pt-edge-missed' : 'pt-edge-taken' });
  }

  return layout(nodes, edges);
}

function layout(nodes: Node<TreeNodeData>[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 64, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.id, { width: n.width ?? 150, height: n.height ?? 40 });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return {
    nodes: nodes.map((n) => {
      const p = g.node(n.id);
      return { ...n, position: { x: p.x - (n.width ?? 0) / 2, y: p.y - (n.height ?? 0) / 2 } };
    }),
    edges,
  };
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '–';
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : `${Math.round(ms)}ms`;
}

export function fmtTokens(n: number | null | undefined): string {
  if (!n) return '0';
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function fmtUsd(v: number | null | undefined): string {
  if (v == null) return 'unpriced';
  if (v === 0) return '$0';
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`;
}

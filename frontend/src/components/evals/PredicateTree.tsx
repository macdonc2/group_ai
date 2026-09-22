import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Check, X, Wrench, Database, Cpu } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { FsmTopology, TurnTrace } from '../../types';
import { buildTree, fmtMs, fmtTokens, type EndData, type GhostData, type TreeNodeData, type VisitData } from './treeModel';

function useDarkMode() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  useEffect(() => {
    const obs = new MutationObserver(() => setDark(document.documentElement.classList.contains('dark')));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

function VisitNode({ data }: NodeProps<Node<VisitData>>) {
  const d = data;
  return (
    <div
      className={cn(
        'rounded-lg border bg-white dark:bg-slate-800 shadow-sm px-3 py-2 text-left w-[236px] cursor-pointer',
        d.status === 'forbidden' && 'border-red-500 ring-1 ring-red-500/40',
        d.status === 'expected' && 'border-emerald-500',
        d.status === 'neutral' && 'border-slate-300 dark:border-slate-600',
        d.selected && 'ring-2 ring-blue-500',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-400 !w-1.5 !h-1.5" />
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-xs text-slate-900 dark:text-slate-100 truncate">{d.name}</span>
        <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 shrink-0">{fmtMs(d.span.duration_ms)}</span>
      </div>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-500 dark:text-slate-400">
        {d.llmCalls > 0 && (
          <span className="inline-flex items-center gap-0.5" title="LLM calls · tokens">
            <Cpu size={10} /> {d.llmCalls} · {fmtTokens(d.tokens)}
          </span>
        )}
        {d.tools.length > 0 && (
          <span className="inline-flex items-center gap-0.5 truncate" title="Tool calls">
            <Wrench size={10} /> {d.tools.join(', ')}
          </span>
        )}
        {d.retrievals > 0 && (
          <span className="inline-flex items-center gap-0.5" title="Retrieval hits">
            <Database size={10} /> {d.retrievals}
          </span>
        )}
      </div>
      {d.decisions.slice(0, 4).map((dec, i) => (
        <div key={i} className="flex items-center gap-1 mt-1 text-[10px] leading-4" title={JSON.stringify(dec.inputs)}>
          {dec.result ? (
            <Check size={11} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
          ) : (
            <X size={11} className="text-slate-400 shrink-0" />
          )}
          <span className="font-mono truncate text-slate-700 dark:text-slate-300">{dec.predicate}</span>
        </div>
      ))}
      <Handle type="source" position={Position.Bottom} className="!bg-slate-400 !w-1.5 !h-1.5" />
    </div>
  );
}

function GhostNode({ data }: NodeProps<Node<GhostData>>) {
  return (
    <div
      className={cn(
        'rounded-md border border-dashed px-2 py-1.5 text-[11px] w-[150px] text-center',
        data.missed
          ? 'border-red-500 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30'
          : 'border-slate-300 dark:border-slate-600 text-slate-400 dark:text-slate-500 bg-slate-50 dark:bg-slate-900/40',
      )}
      title={data.missed ? 'Expected by the case but never reached' : 'Branch not taken'}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      {data.label && <div className="text-[9px] italic opacity-80 leading-3">{data.label}</div>}
      {data.name}
      {data.missed && <span className="ml-1 font-semibold">· expected</span>}
    </div>
  );
}

function EndNode({ data }: NodeProps<Node<EndData>>) {
  return (
    <div
      className={cn(
        'rounded-full px-3 py-1.5 text-[11px] font-semibold w-[110px] text-center border',
        data.error
          ? 'border-red-500 text-red-600 bg-red-50 dark:bg-red-950/30'
          : 'border-slate-400 text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800',
      )}
      title={data.error ?? 'Workflow result returned'}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      {data.error ? 'Error' : 'End'}
    </div>
  );
}

const nodeTypes = { visit: VisitNode, ghost: GhostNode, end: EndNode };

interface PredicateTreeProps {
  trace: TurnTrace;
  topology: FsmTopology | null;
  expect?: { route?: string[] | null; forbid_nodes?: string[] } | null;
  selectedSeq: number | null;
  onSelect: (seq: number | null) => void;
}

export function PredicateTree({ trace, topology, expect, selectedSeq, onSelect }: PredicateTreeProps) {
  const dark = useDarkMode();
  const box = useRef<HTMLDivElement>(null);
  const { nodes, edges } = useMemo(
    () => buildTree(trace, topology, expect, selectedSeq),
    [trace, topology, expect, selectedSeq],
  );

  // Start readable rather than fit-to-screen: long ReAct spines would shrink to
  // illegible. Fit the graph's width (capped at 1x), anchor at the top, pan to see more.
  const onInit = (rf: ReactFlowInstance<Node<TreeNodeData>>) => {
    const w = box.current?.clientWidth ?? 800;
    const xs = nodes.map((n) => [n.position.x, n.position.x + (n.width ?? 0)]).flat();
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const zoom = Math.max(0.55, Math.min(1, (w - 32) / Math.max(maxX - minX, 1)));
    rf.setViewport({ x: (w - (maxX - minX) * zoom) / 2 - minX * zoom, y: 12, zoom });
  };

  return (
    <div ref={box} className="predicate-tree h-full w-full">
      <ReactFlow<Node<TreeNodeData>>
        key={trace.started_at ?? trace.user_input}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode={dark ? 'dark' : 'light'}
        onInit={onInit}
        minZoom={0.2}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onSelect(n.data.kind === 'visit' ? (n.data as VisitData).span.seq : null)}
        onPaneClick={() => onSelect(null)}
      >
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

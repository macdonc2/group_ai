import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { X, RefreshCw, Trash2, Maximize2, Search, SlidersHorizontal, Eraser, Share2, Sparkles, CircleDot } from 'lucide-react';
import { api } from '../../lib/api';
import { GraphAskPanel, type GraphAskResponse } from './GraphAskPanel';
import { GraphFilters } from './GraphFilters';
import { NodeDetails } from './NodeDetails';
import {
  applyFilter,
  buildIndex,
  linkKey,
  nodeColor,
  searchNodes,
  shortestPath,
  type GraphData,
  type GraphLink,
  type GraphNode,
  type Neighbor,
} from './graphModel';

interface KnowledgeGraphProps {
  isOpen: boolean;
  onClose: () => void;
}

type SimNode = GraphNode & { x?: number; y?: number };
type SimLink = { source: string | SimNode; target: string | SimNode; type: string; label: string };

const EMPTY: GraphData = { nodes: [], links: [], stats: { total_nodes: 0, total_links: 0, node_types: {}, edge_types: {} } };
const MAX_AUTO_ZOOM = 2.5;
type MobileView = 'graph' | 'ask' | 'node' | 'filters';

/**
 * The part of the screen that is actually visible. On phones the on-screen
 * keyboard shrinks the visual viewport without resizing the page, so a
 * full-screen sheet has to follow it or its input ends up under the keyboard.
 */
function useVisibleViewport(active: boolean) {
  const [box, setBox] = useState<{ top: number; height: number; keyboard: boolean } | null>(null);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!active || !viewport) return;
    const update = () =>
      setBox({
        top: viewport.offsetTop,
        height: viewport.height,
        keyboard: window.innerHeight - viewport.height > 120,
      });
    update();
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
    return () => {
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
    };
  }, [active]);
  return box;
}

const endId = (end: string | SimNode) => (typeof end === 'string' ? end : end.id);

export function KnowledgeGraph({ isOpen, onClose }: KnowledgeGraphProps) {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [ForceGraph, setForceGraph] = useState<React.ComponentType<any> | null>(null);
  const [graphLibFailed, setGraphLibFailed] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Explorer state
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hiddenNodeTypes, setHiddenNodeTypes] = useState<Set<string>>(new Set());
  const [hiddenEdgeTypes, setHiddenEdgeTypes] = useState<Set<string>>(new Set());
  const [focusDepth, setFocusDepth] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [pathLinks, setPathLinks] = useState<Set<string>>(new Set());
  const [pickingPath, setPickingPath] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<'ask' | 'node'>('ask');
  // Phones show one thing at a time, switched from the bottom bar
  const [mobileView, setMobileView] = useState<MobileView>('graph');
  const viewport = useVisibleViewport(isOpen);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && !ForceGraph && !graphLibFailed) {
      import('react-force-graph-2d')
        .then((mod) => setForceGraph(() => mod.default))
        .catch((err) => {
          console.error('Failed to load graph library:', err);
          setGraphLibFailed(true);
        });
    }
  }, [isOpen, ForceGraph, graphLibFailed]);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGraphData(await api.getKnowledgeGraph());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load knowledge graph');
    } finally {
      setLoading(false);
    }
  }, []);

  const clearMarks = useCallback(() => {
    setHighlight(new Set());
    setPathLinks(new Set());
    setNotice(null);
    setPickingPath(false);
  }, []);

  const handleClear = useCallback(async () => {
    if (!confirm('Are you sure you want to clear your knowledge graph? This cannot be undone.')) return;
    setLoading(true);
    try {
      await api.clearKnowledgeGraph();
      setGraphData(EMPTY);
      setSelectedId(null);
      clearMarks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear knowledge graph');
    } finally {
      setLoading(false);
    }
  }, [clearMarks]);

  useEffect(() => {
    if (isOpen) loadGraph();
  }, [isOpen, loadGraph]);

  // Size the canvas to its container (panels open/close, window resizes)
  useEffect(() => {
    const el = canvasRef.current;
    if (!isOpen || !el) return;
    const update = () => setDimensions({ width: el.clientWidth, height: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [isOpen, graphData]);

  const data = graphData ?? EMPTY;
  const index = useMemo(() => buildIndex(data), [data]);
  const selectedNode = selectedId ? (index.byId.get(selectedId) ?? null) : null;

  const allowed = useCallback(
    (nb: Neighbor) => !hiddenEdgeTypes.has(nb.link.type) && !hiddenNodeTypes.has(nb.node.type),
    [hiddenEdgeTypes, hiddenNodeTypes],
  );

  const visible = useMemo(
    () =>
      applyFilter(data, index, {
        hiddenNodeTypes,
        hiddenEdgeTypes,
        focus: selectedId && focusDepth ? { id: selectedId, depth: focusDepth } : null,
      }),
    [data, index, hiddenNodeTypes, hiddenEdgeTypes, selectedId, focusDepth],
  );

  // Keep one object per node across filter changes so the layout doesn't restart.
  const simNodes = useRef(new Map<string, SimNode>());
  const simData = useMemo(() => {
    const cache = simNodes.current;
    const nodes = visible.nodes.map((n) => {
      const existing = cache.get(n.id);
      if (existing) return Object.assign(existing, n);
      const created: SimNode = { ...n };
      cache.set(n.id, created);
      return created;
    });
    const links: SimLink[] = visible.links.map((l) => ({ ...l }));
    return { nodes, links };
  }, [visible]);

  const matches = useMemo(() => searchNodes(visible.nodes, query), [visible.nodes, query]);
  // What stands out: search matches win, then agent/path highlights.
  const emphasis = query.trim() ? matches : highlight;

  const zoomTo = useCallback((ids: Set<string>) => {
    if (!ids.size) return;
    setTimeout(() => {
      const graph = graphRef.current;
      const points = [...ids].map((id) => simNodes.current.get(id)).filter((n) => n?.x != null && n?.y != null);
      if (!graph || !points.length) return;
      const xs = points.map((n) => n!.x!);
      const ys = points.map((n) => n!.y!);
      const spanX = Math.max(...xs) - Math.min(...xs) + 80;
      const spanY = Math.max(...ys) - Math.min(...ys) + 80;
      const el = canvasRef.current;
      // Fit the marked nodes, but never zoom so far that a couple of nodes fill the canvas
      const scale = Math.min(MAX_AUTO_ZOOM, (el?.clientWidth ?? 800) / spanX, (el?.clientHeight ?? 600) / spanY);
      graph.centerAt((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, 600);
      graph.zoom(scale, 600);
    }, 250);
  }, []);

  // Fit the whole graph once its first layout settles
  const fitted = useRef(false);
  const handleEngineStop = useCallback(() => {
    if (fitted.current) return;
    fitted.current = true;
    graphRef.current?.zoomToFit(400, 60);
  }, []);
  useEffect(() => {
    if (!isOpen) fitted.current = false;
  }, [isOpen]);

  const toggle = (set: Set<string>, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  const applyAnswer = useCallback(
    (response: GraphAskResponse, reveal = false) => {
      const ids = new Set(response.highlight_node_ids.filter((id) => index.byId.has(id)));
      if (reveal) setMobileView('graph');
      setQuery('');
      setPathLinks(new Set());
      setHighlight(ids);
      setFocusDepth(null);
      if (response.filter) {
        const { node_types, edge_types } = response.filter;
        if (node_types.length) {
          setHiddenNodeTypes(new Set(Object.keys(data.stats.node_types).filter((t) => !node_types.includes(t))));
        }
        if (edge_types.length) {
          setHiddenEdgeTypes(new Set(Object.keys(data.stats.edge_types ?? {}).filter((t) => !edge_types.includes(t))));
        }
        setNotice('Filter applied from the assistant');
      } else {
        // Make sure highlighted nodes aren't hidden by a stale filter
        const types = new Set([...ids].map((id) => index.byId.get(id)!.type));
        setHiddenNodeTypes((prev) => new Set([...prev].filter((t) => !types.has(t))));
        setNotice(ids.size ? `${ids.size} node${ids.size === 1 ? '' : 's'} highlighted` : null);
      }
      zoomTo(ids);
    },
    [data, index, zoomTo],
  );

  const handleNodeClick = useCallback(
    (node: SimNode) => {
      if (pickingPath && selectedId && node.id !== selectedId) {
        const path = shortestPath(index, selectedId, node.id, allowed);
        setPickingPath(false);
        if (!path) {
          setNotice('No path between those nodes with the current filters');
          return;
        }
        const ids = new Set(path.nodes);
        setHighlight(ids);
        setPathLinks(new Set(path.links.map(linkKey)));
        setFocusDepth(null);
        setNotice(`Path: ${path.nodes.map((id) => index.byId.get(id)?.label).join(' → ')}`);
        zoomTo(ids);
        return;
      }
      setSelectedId(node.id);
      setTab('node');
    },
    [pickingPath, selectedId, index, allowed, zoomTo],
  );

  const selectById = useCallback(
    (id: string) => {
      setSelectedId(id);
      const node = simNodes.current.get(id);
      if (node?.x != null && node.y != null) graphRef.current?.centerAt(node.x, node.y, 500);
    },
    [],
  );

  const showSheet = (view: MobileView) => {
    setMobileView(view);
    if (view === 'ask' || view === 'node') setTab(view);
  };

  if (!isOpen) return null;

  const hasGraph = data.nodes.length > 0;
  const dimmed = emphasis.size > 0;
  const marked = highlight.size > 0 || pathLinks.size > 0;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      style={viewport ? { top: viewport.top, height: viewport.height, bottom: 'auto' } : undefined}
    >
      <div className="bg-gray-900 rounded-none sm:rounded-lg shadow-xl w-full h-full sm:w-[95vw] sm:h-[90%] flex flex-col overflow-hidden">
        {/* Header. The app draws under the iPhone status bar, so keep the buttons below it. */}
        <div
          className="flex flex-wrap items-center gap-2 sm:gap-3 px-2 pb-2 sm:px-3 sm:pb-3 border-b border-gray-700 shrink-0"
          style={{ paddingTop: 'max(env(safe-area-inset-top), 0.5rem)' }}
        >
          <div className="min-w-0 flex-1 sm:flex-none">
            <h2 className="text-base sm:text-lg font-semibold text-white truncate">Knowledge Graph</h2>
            {graphData && (
              <p className="text-xs text-gray-400">
                {visible.nodes.length === data.nodes.length
                  ? `${data.nodes.length} nodes · ${data.links.length} links`
                  : `${visible.nodes.length} of ${data.nodes.length} nodes · ${visible.links.length} links`}
              </p>
            )}
          </div>

          <div className="relative order-last w-full sm:order-none sm:w-auto sm:flex-1 min-w-0 sm:max-w-sm sm:ml-4">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find nodes…"
              className="w-full rounded-lg bg-gray-800 border border-gray-700 pl-8 pr-10 py-1.5 text-base sm:text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
            {query.trim() && (
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-gray-500">{matches.size}</span>
            )}
          </div>

          <div className="flex items-center gap-1 shrink-0 sm:ml-auto">
            <button
              onClick={() => graphRef.current?.zoomToFit(400, 50)}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded touch-manipulation"
              title="Fit to view"
            >
              <Maximize2 size={18} />
            </button>
            <button
              onClick={loadGraph}
              disabled={loading}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded disabled:opacity-50 touch-manipulation"
              title="Refresh"
            >
              <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={handleClear}
              disabled={loading}
              className="hidden sm:block p-2 text-red-400 hover:text-red-300 hover:bg-gray-700 rounded disabled:opacity-50"
              title="Clear graph"
            >
              <Trash2 size={18} />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-white sm:text-gray-400 hover:text-white bg-gray-700 sm:bg-transparent hover:bg-gray-700 rounded-lg sm:rounded touch-manipulation"
              title="Close"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Body: filters | canvas | ask + details */}
        <div className="flex-1 min-h-0 flex relative">
          {hasGraph && (
            <aside
              className={`${mobileView === 'filters' ? 'absolute inset-0 z-20' : 'hidden'} lg:static lg:block lg:w-56 shrink-0 bg-gray-900 lg:border-r border-gray-700`}
            >
              <GraphFilters
                nodeTypes={data.stats.node_types}
                edgeTypes={data.stats.edge_types ?? {}}
                hiddenNodeTypes={hiddenNodeTypes}
                hiddenEdgeTypes={hiddenEdgeTypes}
                onToggleNodeType={(t) => setHiddenNodeTypes((s) => toggle(s, t))}
                onToggleEdgeType={(t) => setHiddenEdgeTypes((s) => toggle(s, t))}
                onOnlyNodeType={(t) =>
                  setHiddenNodeTypes(new Set(Object.keys(data.stats.node_types).filter((x) => x !== t)))
                }
                onOnlyEdgeType={(t) =>
                  setHiddenEdgeTypes(new Set(Object.keys(data.stats.edge_types ?? {}).filter((x) => x !== t)))
                }
                onReset={() => {
                  setHiddenNodeTypes(new Set());
                  setHiddenEdgeTypes(new Set());
                }}
              />
            </aside>
          )}

          <div ref={canvasRef} className="flex-1 min-w-0 relative overflow-hidden">
            {loading && !graphData && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
              </div>
            )}

            {error && (
              <div className="absolute inset-0 flex items-center justify-center z-10 bg-gray-900">
                <div className="text-center px-4">
                  <p className="text-red-400 mb-4">{error}</p>
                  <button onClick={loadGraph} className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                    Retry
                  </button>
                </div>
              </div>
            )}

            {graphData && !hasGraph && !error && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center text-gray-400">
                  <p className="text-lg mb-2">No knowledge graph data yet</p>
                  <p className="text-sm">Start chatting to build your knowledge graph!</p>
                </div>
              </div>
            )}

            {hasGraph && visible.nodes.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center text-gray-400 text-sm">
                Every node is filtered out. Reset the filters to see the graph.
              </div>
            )}

            {hasGraph && !ForceGraph && !graphLibFailed && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
              </div>
            )}

            {/* Fallback list when the graph library can't load */}
            {hasGraph && graphLibFailed && (
              <div className="absolute inset-0 overflow-auto p-4">
                <p className="text-yellow-400 text-sm text-center mb-4">
                  Graph drawing is unavailable on this device; showing a list instead.
                </p>
                <div className="max-w-2xl mx-auto space-y-1.5">
                  {visible.nodes
                    .filter((n) => !dimmed || emphasis.has(n.id))
                    .slice(0, 200)
                    .map((node) => (
                      <button
                        key={node.id}
                        onClick={() => handleNodeClick(node)}
                        className="w-full flex items-center gap-2 p-2.5 bg-gray-800/50 rounded-lg hover:bg-gray-700/50 text-left"
                      >
                        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: nodeColor(node.type) }} />
                        <span className="text-gray-200 text-sm truncate">{node.fullLabel}</span>
                        <span className="text-gray-500 text-xs ml-auto capitalize">{node.type}</span>
                      </button>
                    ))}
                </div>
              </div>
            )}

            {hasGraph && ForceGraph && (
              <ForceGraph
                ref={graphRef}
                graphData={simData}
                width={dimensions.width}
                height={dimensions.height}
                backgroundColor="#111827"
                nodeLabel={(node: SimNode) => `${node.fullLabel} · ${node.type}`}
                linkLabel={(link: SimLink) => link.label}
                linkColor={(link: SimLink) => {
                  const key = linkKey({ ...link, source: endId(link.source), target: endId(link.target) } as GraphLink);
                  if (pathLinks.has(key)) return '#fbbf24';
                  const lit = emphasis.has(endId(link.source)) && emphasis.has(endId(link.target));
                  return dimmed && !lit ? 'rgba(75,85,99,0.25)' : '#6b7280';
                }}
                linkWidth={(link: SimLink) =>
                  pathLinks.has(linkKey({ ...link, source: endId(link.source), target: endId(link.target) } as GraphLink)) ? 3 : 1
                }
                linkDirectionalArrowLength={4}
                linkDirectionalArrowRelPos={1}
                onNodeClick={handleNodeClick}
                onEngineStop={handleEngineStop}
                cooldownTicks={120}
                onBackgroundClick={() => setPickingPath(false)}
                nodePointerAreaPaint={(node: SimNode, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
                  // Keep a finger-sized target on screen however far the graph is zoomed out
                  ctx.fillStyle = color;
                  ctx.beginPath();
                  ctx.arc(node.x ?? 0, node.y ?? 0, Math.max(10, 16 / globalScale), 0, 2 * Math.PI);
                  ctx.fill();
                }}
                nodeCanvasObject={(node: SimNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
                  const x = node.x ?? 0;
                  const y = node.y ?? 0;
                  const lit = !dimmed || emphasis.has(node.id);
                  const radius = 4 + Math.min(5, Math.sqrt(node.degree ?? 1));
                  ctx.globalAlpha = lit ? 1 : 0.18;
                  ctx.beginPath();
                  ctx.arc(x, y, radius, 0, 2 * Math.PI);
                  ctx.fillStyle = node.color;
                  ctx.fill();
                  if (dimmed && lit) {
                    ctx.lineWidth = 2 / globalScale;
                    ctx.strokeStyle = '#fbbf24';
                    ctx.stroke();
                  }
                  if (node.id === selectedId) {
                    ctx.beginPath();
                    ctx.arc(x, y, radius + 3 / globalScale + 1.5, 0, 2 * Math.PI);
                    ctx.lineWidth = 2 / globalScale;
                    ctx.strokeStyle = '#ffffff';
                    ctx.stroke();
                  }
                  // Labels: always for emphasised/selected nodes, otherwise once zoomed in enough
                  if ((dimmed && lit) || node.id === selectedId || (lit && globalScale > 0.9)) {
                    const fontSize = 12 / globalScale;
                    ctx.font = `${fontSize}px Sans-Serif`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'top';
                    ctx.fillStyle = dimmed && lit ? '#f3f4f6' : '#9ca3af';
                    ctx.fillText(node.label, x, y + radius + 2);
                  }
                  ctx.globalAlpha = 1;
                }}
              />
            )}

            {/* Phones: tapping a node keeps the graph in view and offers the next step */}
            {selectedNode && (
              <div className="lg:hidden absolute bottom-2 left-2 right-2 flex items-center gap-2 bg-gray-800/95 border border-gray-700 rounded-xl px-3 py-2">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: nodeColor(selectedNode.type) }} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-white truncate">{selectedNode.label}</p>
                  <p className="text-xs text-gray-400 capitalize">
                    {pickingPath ? 'Tap another node for the path' : selectedNode.type}
                  </p>
                </div>
                <button
                  onClick={() => showSheet('node')}
                  className="px-3 py-1.5 rounded-lg bg-gray-700 text-gray-100 text-xs touch-manipulation"
                >
                  Details
                </button>
                <button
                  onClick={() => showSheet('ask')}
                  className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs touch-manipulation"
                >
                  Ask
                </button>
                <button
                  onClick={() => {
                    setSelectedId(null);
                    setFocusDepth(null);
                    setPickingPath(false);
                  }}
                  className="p-1.5 text-gray-400 touch-manipulation"
                  aria-label="Deselect node"
                >
                  <X size={16} />
                </button>
              </div>
            )}

            {(notice || marked) && (
              <div className="absolute top-2 left-2 right-2 flex justify-center pointer-events-none">
                <div className="pointer-events-auto flex items-center gap-2 max-w-full bg-gray-800/95 border border-gray-700 rounded-full pl-3 pr-1.5 py-1 text-xs text-gray-200">
                  <span className="truncate">{notice ?? 'Highlight active'}</span>
                  <button
                    onClick={clearMarks}
                    className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-700 hover:bg-gray-600 shrink-0"
                  >
                    <Eraser size={12} /> Clear
                  </button>
                </div>
              </div>
            )}
          </div>

          {hasGraph && (
            <aside
              className={`${mobileView === 'ask' || mobileView === 'node' ? 'absolute inset-0 z-20 flex' : 'hidden'} lg:static lg:flex lg:w-96 shrink-0 bg-gray-900 lg:border-l border-gray-700 flex-col min-h-0`}
            >
              <div className="hidden lg:flex shrink-0 border-b border-gray-700 text-sm">
                {(['ask', 'node'] as const).map((key) => (
                  <button
                    key={key}
                    onClick={() => setTab(key)}
                    className={`flex-1 py-2 ${tab === key ? 'text-white border-b-2 border-blue-500' : 'text-gray-400 hover:text-gray-200'}`}
                  >
                    {key === 'ask' ? 'Ask' : 'Node'}
                  </button>
                ))}
              </div>
              <div className={`flex-1 min-h-0 ${tab === 'ask' ? '' : 'hidden'}`}>
                <GraphAskPanel
                  selectedNodeId={selectedId}
                  selectedLabel={selectedNode?.fullLabel ?? null}
                  onApply={applyAnswer}
                  pending={pendingQuestion}
                  onPendingConsumed={() => setPendingQuestion(null)}
                />
              </div>
              {tab === 'node' && (
                <div className="flex-1 min-h-0">
                  <NodeDetails
                    node={selectedNode}
                    index={index}
                    focusDepth={focusDepth}
                    pickingPath={pickingPath}
                    onSelect={selectById}
                    onFocus={(depth) => {
                      setFocusDepth(depth);
                      setMobileView('graph');
                    }}
                    onStartPath={() => {
                      setPickingPath((p) => !p);
                      setMobileView('graph');
                    }}
                    onAsk={(question) => {
                      setPendingQuestion(question);
                      showSheet('ask');
                    }}
                  />
                </div>
              )}
            </aside>
          )}
        </div>

        {/* Phone navigation: one view at a time. Hidden while typing so the keyboard has room. */}
        {hasGraph && !viewport?.keyboard && (
          <nav
            className="lg:hidden shrink-0 grid grid-cols-4 border-t border-gray-700 bg-gray-900"
            style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
          >
            {(
              [
                ['graph', 'Graph', Share2],
                ['ask', 'Ask', Sparkles],
                ['node', 'Node', CircleDot],
                ['filters', 'Filters', SlidersHorizontal],
              ] as const
            ).map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => showSheet(key)}
                aria-current={mobileView === key}
                className={`relative flex flex-col items-center gap-0.5 py-2 text-[11px] touch-manipulation ${
                  mobileView === key ? 'text-blue-400' : 'text-gray-400'
                }`}
              >
                <Icon size={20} />
                {label}
                {key === 'filters' && (hiddenNodeTypes.size > 0 || hiddenEdgeTypes.size > 0) && (
                  <span className="absolute top-1.5 left-1/2 ml-2 w-2 h-2 rounded-full bg-blue-500" />
                )}
                {key === 'graph' && marked && mobileView !== 'graph' && (
                  <span className="absolute top-1.5 left-1/2 ml-2 w-2 h-2 rounded-full bg-amber-400" />
                )}
              </button>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback, useRef } from 'react';
import { X, RefreshCw, Trash2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { api } from '../../lib/api';

interface GraphNode {
  id: string;
  label: string;
  fullLabel: string;
  type: string;
  color: string;
  properties: Record<string, unknown>;
}

interface GraphLink {
  source: string;
  target: string;
  type: string;
  label: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: {
    total_nodes: number;
    total_links: number;
    node_types: Record<string, number>;
  };
}

interface KnowledgeGraphProps {
  isOpen: boolean;
  onClose: () => void;
}

export function KnowledgeGraph({ isOpen, onClose }: KnowledgeGraphProps) {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [ForceGraph, setForceGraph] = useState<React.ComponentType<any> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  
  const [graphLibFailed, setGraphLibFailed] = useState(false);
  
  // Load the graph library when component mounts
  useEffect(() => {
    if (isOpen && !ForceGraph && !graphLibFailed) {
      import('react-force-graph-2d').then(mod => {
        setForceGraph(() => mod.default);
      }).catch(err => {
        console.error('Failed to load graph library:', err);
        setGraphLibFailed(true);
        // Don't set error - we'll show fallback view instead
      });
    }
  }, [isOpen, ForceGraph, graphLibFailed]);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getKnowledgeGraph();
      setGraphData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load knowledge graph');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleClear = useCallback(async () => {
    if (!confirm('Are you sure you want to clear your knowledge graph? This cannot be undone.')) {
      return;
    }
    
    setLoading(true);
    try {
      await api.clearKnowledgeGraph();
      setGraphData({ nodes: [], links: [], stats: { total_nodes: 0, total_links: 0, node_types: {} } });
      setSelectedNode(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear knowledge graph');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadGraph();
    }
  }, [isOpen, loadGraph]);

  useEffect(() => {
    if (containerRef.current) {
      const updateDimensions = () => {
        if (containerRef.current) {
          setDimensions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight - 60, // Account for header
          });
        }
      };
      
      updateDimensions();
      window.addEventListener('resize', updateDimensions);
      return () => window.removeEventListener('resize', updateDimensions);
    }
  }, [isOpen]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
  }, []);

  const handleZoomIn = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoom(graphRef.current.zoom() * 1.5, 400);
    }
  }, []);

  const handleZoomOut = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoom(graphRef.current.zoom() / 1.5, 400);
    }
  }, []);

  const handleFit = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(400, 50);
    }
  }, []);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div 
        ref={containerRef}
        className="bg-gray-900 rounded-none sm:rounded-lg shadow-xl w-full h-full sm:w-[90vw] sm:h-[85vh] flex flex-col"
      >
        {/* Header - Mobile optimized */}
        <div className="flex items-center justify-between p-3 sm:p-4 border-b border-gray-700 shrink-0">
          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4 min-w-0">
            <h2 className="text-base sm:text-lg font-semibold text-white truncate">Knowledge Graph</h2>
            {graphData && (
              <div className="flex items-center gap-2 sm:gap-4 text-xs sm:text-sm text-gray-400">
                <span>{graphData.stats.total_nodes} nodes</span>
                <span>{graphData.stats.total_links} links</span>
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-1 sm:gap-2 shrink-0">
            {/* Zoom controls - hidden on very small screens */}
            <div className="hidden xs:flex items-center gap-1 sm:gap-2">
              <button
                onClick={handleZoomIn}
                className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded touch-manipulation"
                title="Zoom In"
              >
                <ZoomIn size={18} />
              </button>
              <button
                onClick={handleZoomOut}
                className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded touch-manipulation"
                title="Zoom Out"
              >
                <ZoomOut size={18} />
              </button>
            </div>
            <button
              onClick={handleFit}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded touch-manipulation"
              title="Fit to View"
            >
              <Maximize2 size={18} />
            </button>
            <div className="hidden sm:block w-px h-6 bg-gray-700 mx-1 sm:mx-2" />
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
              className="hidden sm:block p-2 text-red-400 hover:text-red-300 hover:bg-gray-700 rounded disabled:opacity-50 touch-manipulation"
              title="Clear Graph"
            >
              <Trash2 size={18} />
            </button>
            <div className="w-px h-6 bg-gray-700 mx-1 sm:mx-2" />
            {/* Close button - larger on mobile */}
            <button
              onClick={onClose}
              className="p-2.5 sm:p-2 text-white sm:text-gray-400 hover:text-white bg-gray-700 sm:bg-transparent hover:bg-gray-700 rounded-lg sm:rounded touch-manipulation"
              title="Close"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 relative">
          {loading && !graphData && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <p className="text-red-400 mb-4">{error}</p>
                <button
                  onClick={loadGraph}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {graphData && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <p className="text-lg mb-2">No knowledge graph data yet</p>
                <p className="text-sm">Start chatting to build your knowledge graph!</p>
              </div>
            </div>
          )}

          {graphData && graphData.nodes.length > 0 && !ForceGraph && !graphLibFailed && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
            </div>
          )}

          {/* Fallback list view when graph library fails to load */}
          {graphData && graphData.nodes.length > 0 && graphLibFailed && (
            <div className="absolute inset-0 overflow-auto p-4">
              <div className="max-w-2xl mx-auto">
                <div className="text-center mb-6">
                  <p className="text-yellow-400 text-sm mb-2">Graph visualization unavailable on this device</p>
                  <p className="text-gray-400 text-xs">Showing data in list format instead</p>
                </div>
                
                {/* Group nodes by type */}
                {Object.entries(
                  graphData.nodes.reduce((acc, node) => {
                    if (!acc[node.type]) acc[node.type] = [];
                    acc[node.type].push(node);
                    return acc;
                  }, {} as Record<string, GraphNode[]>)
                ).map(([type, nodes]) => (
                  <div key={type} className="mb-6">
                    <h3 className="text-white font-medium capitalize mb-3 flex items-center gap-2">
                      <span
                        className="w-3 h-3 rounded-full"
                        style={{
                          backgroundColor: 
                            type === 'user' ? '#3b82f6' :
                            type === 'interaction' ? '#10b981' :
                            type === 'topic' ? '#f59e0b' :
                            type === 'tool' ? '#8b5cf6' :
                            type === 'suggestion' ? '#ec4899' : '#6b7280'
                        }}
                      />
                      {type} ({nodes.length})
                    </h3>
                    <div className="space-y-2">
                      {nodes.slice(0, 20).map((node) => (
                        <div
                          key={node.id}
                          onClick={() => handleNodeClick(node)}
                          className="p-3 bg-gray-800/50 rounded-lg cursor-pointer hover:bg-gray-700/50 transition-colors"
                        >
                          <p className="text-gray-200 text-sm">{node.fullLabel}</p>
                        </div>
                      ))}
                      {nodes.length > 20 && (
                        <p className="text-gray-500 text-xs text-center">
                          +{nodes.length - 20} more {type}s
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {graphData && graphData.nodes.length > 0 && ForceGraph && (
            <ForceGraph
              ref={graphRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              nodeLabel={(node: GraphNode) => node.fullLabel}
              nodeColor={(node: GraphNode) => node.color}
              nodeRelSize={6}
              linkLabel={(link: GraphLink) => link.label}
              linkColor={() => '#4b5563'}
              linkWidth={1}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              onNodeClick={(node: GraphNode) => handleNodeClick(node)}
              backgroundColor="#111827"
              nodeCanvasObject={(node: GraphNode & { x: number; y: number }, ctx: CanvasRenderingContext2D, globalScale: number) => {
                const label = node.label;
                const fontSize = 12 / globalScale;
                ctx.font = `${fontSize}px Sans-Serif`;
                
                // Draw node circle
                ctx.beginPath();
                ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
                ctx.fillStyle = node.color;
                ctx.fill();
                
                // Draw label
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                ctx.fillStyle = '#9ca3af';
                ctx.fillText(label, node.x, node.y + 8);
              }}
            />
          )}

          {/* Legend - collapsible on mobile, hidden in fallback mode */}
          {graphData && graphData.nodes.length > 0 && ForceGraph && !graphLibFailed && (
            <div className="absolute bottom-2 sm:bottom-4 left-2 sm:left-4 bg-gray-800/90 rounded-lg p-2 sm:p-3 text-xs sm:text-sm max-w-[45vw] sm:max-w-none">
              <h4 className="text-white font-medium mb-1 sm:mb-2">Node Types</h4>
              <div className="space-y-0.5 sm:space-y-1">
                {Object.entries(graphData.stats.node_types).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-1.5 sm:gap-2">
                    <span
                      className="w-2.5 h-2.5 sm:w-3 sm:h-3 rounded-full shrink-0"
                      style={{
                        backgroundColor: 
                          type === 'user' ? '#3b82f6' :
                          type === 'interaction' ? '#10b981' :
                          type === 'topic' ? '#f59e0b' :
                          type === 'tool' ? '#8b5cf6' :
                          type === 'suggestion' ? '#ec4899' : '#6b7280'
                      }}
                    />
                    <span className="text-gray-300 capitalize truncate">{type}</span>
                    <span className="text-gray-500">({count})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Node Details Panel - full width on mobile */}
          {selectedNode && (
            <div className="absolute inset-x-2 sm:inset-x-auto top-2 sm:top-4 sm:right-4 sm:w-80 bg-gray-800/95 rounded-lg p-3 sm:p-4 text-sm">
              <div className="flex items-center justify-between mb-2 sm:mb-3">
                <h4 className="text-white font-medium">Node Details</h4>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 text-gray-400 hover:text-white touch-manipulation"
                >
                  <X size={18} />
                </button>
              </div>
              <div className="space-y-2">
                <div>
                  <span className="text-gray-400">Type:</span>
                  <span className="ml-2 text-white capitalize">{selectedNode.type}</span>
                </div>
                <div>
                  <span className="text-gray-400">Label:</span>
                  <p className="text-white mt-1 break-words">{selectedNode.fullLabel}</p>
                </div>
                {Object.keys(selectedNode.properties).length > 0 && (
                  <div>
                    <span className="text-gray-400">Properties:</span>
                    <pre className="mt-1 text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-auto max-h-32 sm:max-h-40">
                      {JSON.stringify(selectedNode.properties, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

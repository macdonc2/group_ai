import { ArrowLeft, ArrowRight, Focus, MessageCircleQuestion, Route } from 'lucide-react';
import { nodeColor, type GraphIndex, type GraphNode } from './graphModel';

interface NodeDetailsProps {
  node: GraphNode | null;
  index: GraphIndex;
  focusDepth: number | null;
  pickingPath: boolean;
  onSelect: (id: string) => void;
  onFocus: (depth: number | null) => void;
  onStartPath: () => void;
  onAsk: (question: string) => void;
}

export function NodeDetails({ node, index, focusDepth, pickingPath, onSelect, onFocus, onStartPath, onAsk }: NodeDetailsProps) {
  if (!node) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Click a node to see what is stored about it and what it links to.
      </div>
    );
  }
  const neighbors = index.adjacency.get(node.id) ?? [];
  const properties = Object.entries(node.properties);

  return (
    <div className="h-full overflow-y-auto p-3 text-sm space-y-4">
      <div>
        <div className="flex items-center gap-2 text-xs text-gray-400 capitalize">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: nodeColor(node.type) }} />
          {node.type}
        </div>
        <p className="text-white font-medium mt-1 break-words">{node.fullLabel}</p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="flex items-center gap-1 text-xs text-gray-400">
            <Focus size={13} /> Neighbourhood
          </span>
          {[1, 2, 3].map((depth) => (
            <button
              key={depth}
              onClick={() => onFocus(focusDepth === depth ? null : depth)}
              className={`px-2 py-1 rounded text-xs ${
                focusDepth === depth ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
              title={`Show only nodes within ${depth} hop${depth > 1 ? 's' : ''}`}
            >
              {depth} hop{depth > 1 ? 's' : ''}
            </button>
          ))}
          {focusDepth !== null && (
            <button onClick={() => onFocus(null)} className="text-xs text-blue-400 hover:text-blue-300">
              Show all
            </button>
          )}
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={onStartPath}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
              pickingPath ? 'bg-amber-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            <Route size={13} /> {pickingPath ? 'Click another node…' : 'Find path to…'}
          </button>
          <button
            onClick={() => onAsk(`Tell me about ${node.fullLabel} and how it connects to the rest of my graph.`)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-800 text-gray-300 hover:bg-gray-700"
          >
            <MessageCircleQuestion size={13} /> Ask about this
          </button>
        </div>
      </div>

      {properties.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-1">Properties</h4>
          <dl className="space-y-1">
            {properties.map(([key, value]) => (
              <div key={key} className="grid grid-cols-[7rem_1fr] gap-2">
                <dt className="text-gray-400 truncate" title={key}>
                  {key.replace(/_/g, ' ')}
                </dt>
                <dd className="text-gray-200 break-words min-w-0">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div>
        <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-1">Links ({neighbors.length})</h4>
        {neighbors.length === 0 && <p className="text-gray-500">No links.</p>}
        <ul className="space-y-0.5">
          {neighbors.map((nb, i) => (
            <li key={i}>
              <button
                onClick={() => onSelect(nb.node.id)}
                className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded hover:bg-gray-800 text-left"
              >
                {nb.outgoing ? (
                  <ArrowRight size={12} className="text-gray-500 shrink-0" />
                ) : (
                  <ArrowLeft size={12} className="text-gray-500 shrink-0" />
                )}
                <span className="text-xs text-gray-400 shrink-0">{nb.link.label}</span>
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: nodeColor(nb.node.type) }} />
                <span className="text-gray-200 truncate">{nb.node.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

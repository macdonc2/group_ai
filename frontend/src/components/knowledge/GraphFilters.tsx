import { nodeColor } from './graphModel';

interface GraphFiltersProps {
  nodeTypes: Record<string, number>;
  edgeTypes: Record<string, number>;
  hiddenNodeTypes: Set<string>;
  hiddenEdgeTypes: Set<string>;
  onToggleNodeType: (type: string) => void;
  onToggleEdgeType: (type: string) => void;
  onOnlyNodeType: (type: string) => void;
  onOnlyEdgeType: (type: string) => void;
  onReset: () => void;
}

function Row({
  label,
  count,
  checked,
  swatch,
  onToggle,
  onOnly,
}: {
  label: string;
  count: number;
  checked: boolean;
  swatch?: string;
  onToggle: () => void;
  onOnly: () => void;
}) {
  return (
    <div className="group flex items-center gap-2 py-0.5">
      <label className="flex items-center gap-2 min-w-0 flex-1 cursor-pointer">
        <input type="checkbox" checked={checked} onChange={onToggle} className="accent-blue-500 shrink-0" />
        {swatch && <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: swatch }} />}
        <span className={`truncate ${checked ? 'text-gray-200' : 'text-gray-500'}`}>{label}</span>
      </label>
      <button
        onClick={onOnly}
        className="text-[11px] text-blue-400 hover:text-blue-300 opacity-0 group-hover:opacity-100 focus:opacity-100"
        title={`Show only ${label}`}
      >
        only
      </button>
      <span className="text-gray-500 tabular-nums text-xs w-6 text-right">{count}</span>
    </div>
  );
}

export function GraphFilters(props: GraphFiltersProps) {
  const filtered = props.hiddenNodeTypes.size > 0 || props.hiddenEdgeTypes.size > 0;
  return (
    <div className="h-full overflow-y-auto p-3 text-sm">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-white font-medium">Filters</h3>
        {filtered && (
          <button onClick={props.onReset} className="text-xs text-blue-400 hover:text-blue-300">
            Reset
          </button>
        )}
      </div>

      <h4 className="text-xs uppercase tracking-wide text-gray-500 mt-2 mb-1">Node types</h4>
      {Object.entries(props.nodeTypes).map(([type, count]) => (
        <Row
          key={type}
          label={type}
          count={count}
          swatch={nodeColor(type)}
          checked={!props.hiddenNodeTypes.has(type)}
          onToggle={() => props.onToggleNodeType(type)}
          onOnly={() => props.onOnlyNodeType(type)}
        />
      ))}

      <h4 className="text-xs uppercase tracking-wide text-gray-500 mt-4 mb-1">Link types</h4>
      {Object.entries(props.edgeTypes).map(([type, count]) => (
        <Row
          key={type}
          label={type.replace(/_/g, ' ').toLowerCase()}
          count={count}
          checked={!props.hiddenEdgeTypes.has(type)}
          onToggle={() => props.onToggleEdgeType(type)}
          onOnly={() => props.onOnlyEdgeType(type)}
        />
      ))}
    </div>
  );
}

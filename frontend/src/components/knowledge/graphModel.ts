// Pure graph helpers for the explorer: filtering, neighbourhoods and paths.
// Mirrors the server-side GraphSnapshot so manual exploration and the agent agree.

export interface GraphNode {
  id: string;
  label: string;
  fullLabel: string;
  type: string;
  color: string;
  degree?: number;
  properties: Record<string, unknown>;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
  label: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: {
    total_nodes: number;
    total_links: number;
    node_types: Record<string, number>;
    edge_types?: Record<string, number>;
  };
}

export interface Neighbor {
  node: GraphNode;
  link: GraphLink;
  outgoing: boolean;
}

export interface GraphIndex {
  byId: Map<string, GraphNode>;
  adjacency: Map<string, Neighbor[]>;
  ownerId: string | null;
}

export const NODE_TYPE_COLORS: Record<string, string> = {
  user: '#3b82f6',
  interaction: '#10b981',
  topic: '#f59e0b',
  tool: '#8b5cf6',
  suggestion: '#ec4899',
  person: '#06b6d4',
  pet: '#84cc16',
  location: '#f97316',
  preference: '#eab308',
  pattern: '#14b8a6',
  thread: '#a855f7',
  expertise: '#f43f5e',
  entity: '#0ea5e9',
  intent: '#64748b',
  contradiction: '#ef4444',
};

export function nodeColor(type: string): string {
  return NODE_TYPE_COLORS[type] ?? '#6b7280';
}

export const linkKey = (l: GraphLink) => `${l.source}|${l.type}|${l.target}`;

export function buildIndex(data: GraphData): GraphIndex {
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const adjacency = new Map<string, Neighbor[]>(data.nodes.map((n) => [n.id, []]));
  for (const link of data.links) {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target) continue;
    adjacency.get(source.id)!.push({ node: target, link, outgoing: true });
    if (source.id !== target.id) adjacency.get(target.id)!.push({ node: source, link, outgoing: false });
  }
  const ownerId = data.nodes.find((n) => n.type === 'user')?.id ?? null;
  return { byId, adjacency, ownerId };
}

/** Ids within `depth` hops of a node, following only links that pass `allow`. */
export function neighborhood(
  index: GraphIndex,
  startId: string,
  depth: number,
  allow: (n: Neighbor) => boolean = () => true,
): Set<string> {
  const seen = new Set([startId]);
  let frontier = [startId];
  for (let hop = 0; hop < depth && frontier.length; hop++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const nb of index.adjacency.get(id) ?? []) {
        if (seen.has(nb.node.id) || !allow(nb)) continue;
        seen.add(nb.node.id);
        next.push(nb.node.id);
      }
    }
    frontier = next;
  }
  return seen;
}

function bfsPath(
  index: GraphIndex,
  from: string,
  to: string,
  allow: (n: Neighbor) => boolean,
  avoid: string | null,
): { nodes: string[]; links: GraphLink[] } | null {
  if (from === to) return { nodes: [from], links: [] };
  const prev = new Map<string, { id: string; link: GraphLink } | null>([[from, null]]);
  const queue = [from];
  while (queue.length) {
    const current = queue.shift()!;
    for (const nb of index.adjacency.get(current) ?? []) {
      const id = nb.node.id;
      if (prev.has(id) || !allow(nb) || (id === avoid && id !== to)) continue;
      prev.set(id, { id: current, link: nb.link });
      if (id === to) {
        const nodes = [to];
        const links: GraphLink[] = [];
        let step = prev.get(to);
        while (step) {
          nodes.unshift(step.id);
          links.unshift(step.link);
          step = prev.get(step.id);
        }
        return { nodes, links };
      }
      queue.push(id);
    }
  }
  return null;
}

/**
 * Shortest chain between two nodes, ignoring direction. Prefers a route that
 * skips the owner's node, since nearly everything is linked through it.
 */
export function shortestPath(
  index: GraphIndex,
  from: string,
  to: string,
  allow: (n: Neighbor) => boolean = () => true,
) {
  const owner = index.ownerId;
  if (owner && owner !== from && owner !== to) {
    const detour = bfsPath(index, from, to, allow, owner);
    if (detour) return detour;
  }
  return bfsPath(index, from, to, allow, null);
}

export interface ViewFilter {
  hiddenNodeTypes: Set<string>;
  hiddenEdgeTypes: Set<string>;
  /** Show only this node's neighbourhood. */
  focus: { id: string; depth: number } | null;
}

export function applyFilter(data: GraphData, index: GraphIndex, filter: ViewFilter) {
  const allow = (nb: Neighbor) =>
    !filter.hiddenEdgeTypes.has(nb.link.type) && !filter.hiddenNodeTypes.has(nb.node.type);
  const within =
    filter.focus && index.byId.has(filter.focus.id)
      ? neighborhood(index, filter.focus.id, filter.focus.depth, allow)
      : null;
  const nodes = data.nodes.filter(
    (n) => (within ? within.has(n.id) : true) && (!filter.hiddenNodeTypes.has(n.type) || n.id === filter.focus?.id),
  );
  const visible = new Set(nodes.map((n) => n.id));
  const links = data.links.filter(
    (l) => !filter.hiddenEdgeTypes.has(l.type) && visible.has(l.source) && visible.has(l.target),
  );
  return { nodes, links };
}

export function searchNodes(nodes: GraphNode[], query: string): Set<string> {
  const q = query.trim().toLowerCase();
  if (!q) return new Set();
  return new Set(
    nodes
      .filter(
        (n) =>
          n.fullLabel.toLowerCase().includes(q) ||
          n.type.includes(q) ||
          JSON.stringify(n.properties).toLowerCase().includes(q),
      )
      .map((n) => n.id),
  );
}

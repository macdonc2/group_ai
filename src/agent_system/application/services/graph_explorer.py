"""In-memory view of one user's knowledge graph: search, filtering, traversal, paths.

A `GraphSnapshot` is built once per request from the graph store and is the only
thing the graph explorer agent can touch. It is read-only and pure Python, so the
same operations back the agent's tools, the unit tests and the offline evals.

Nodes get short handles (`n1`, `n2`, ...) that are stable for a given snapshot.
The agent works in handles rather than UUIDs: they cost a fraction of the tokens,
and anything the agent says about the graph can be checked by resolving the
handle back to a real node.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Literal

Direction = Literal["out", "in", "both"]

MAX_DEPTH = 3
MAX_PATH_HOPS = 6
_PROP_VALUE_CHARS = 160
_HIDDEN_PROPS = {"id", "user_id", "name_lower", "embedding", "properties_json", "node_type", "label"}


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    type: str
    weight: float = 1.0


@dataclass(frozen=True)
class Hop:
    """One step away from a node: the edge taken and where it leads."""

    edge: GraphEdge
    other: str
    outgoing: bool


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _norm(text)) if t]


def clean_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Drop internal fields and clip long values so a node is cheap to show."""
    out: dict[str, Any] = {}
    for key, value in props.items():
        if key in _HIDDEN_PROPS or key.endswith("_lower") or value in (None, "", [], {}):
            continue
        if isinstance(value, str) and len(value) > _PROP_VALUE_CHARS:
            value = value[:_PROP_VALUE_CHARS] + "…"
        elif isinstance(value, (list, tuple)):
            value = [str(v)[:60] for v in list(value)[:8]]
        elif isinstance(value, dict):
            value = {str(k): str(v)[:60] for k, v in list(value.items())[:8]}
        out[str(key)] = value
    return out


class GraphSnapshot:
    """Indexed, immutable copy of a user's graph."""

    def __init__(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        by_id: dict[str, GraphNode] = {}
        for node in nodes:
            if node.id and node.id not in by_id:
                by_id[node.id] = node
        ordered = sorted(by_id.values(), key=lambda n: (n.type, _norm(n.label), n.id))
        self.nodes: list[GraphNode] = ordered
        self._by_id = by_id
        self._handle_of = {n.id: f"n{i}" for i, n in enumerate(ordered, start=1)}
        self._id_of = {h: i for i, h in self._handle_of.items()}

        seen: set[tuple[str, str, str]] = set()
        self.edges: list[GraphEdge] = []
        self._hops: dict[str, list[Hop]] = {n.id: [] for n in ordered}
        for edge in edges:
            key = (edge.source, edge.target, edge.type)
            if edge.source not in by_id or edge.target not in by_id or key in seen:
                continue
            seen.add(key)
            self.edges.append(edge)
            self._hops[edge.source].append(Hop(edge, edge.target, True))
            if edge.target != edge.source:
                self._hops[edge.target].append(Hop(edge, edge.source, False))

    # -- construction ------------------------------------------------------
    @classmethod
    def from_records(cls, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> GraphSnapshot:
        return cls(
            [
                GraphNode(
                    id=str(n["id"]), type=str(n.get("type") or "unknown"),
                    label=str(n.get("label") or n["id"]), properties=dict(n.get("properties") or {}),
                )
                for n in nodes if n.get("id")
            ],
            [
                GraphEdge(
                    source=str(e["source"]), target=str(e["target"]), type=str(e.get("type") or "RELATED"),
                    weight=float(e.get("weight") or 1.0),
                )
                for e in edges if e.get("source") and e.get("target")
            ],
        )

    # -- lookups -----------------------------------------------------------
    def __len__(self) -> int:
        return len(self.nodes)

    def node(self, node_id: str) -> GraphNode | None:
        return self._by_id.get(node_id)

    def handle(self, node_id: str) -> str | None:
        return self._handle_of.get(node_id)

    def resolve(self, ref: str) -> GraphNode | None:
        """Find a node by handle (`n12`) or by its real id."""
        ref = str(ref).strip().strip("[]")
        return self._by_id.get(self._id_of.get(ref.lower(), ref))

    def degree(self, node_id: str) -> int:
        return len(self._hops.get(node_id, []))

    def node_type_counts(self) -> dict[str, int]:
        return dict(Counter(n.type for n in self.nodes).most_common())

    def edge_type_counts(self) -> dict[str, int]:
        return dict(Counter(e.type for e in self.edges).most_common())

    def owner(self) -> GraphNode | None:
        """The node standing for the graph's owner (everything links to it)."""
        return next((n for n in self.nodes if n.type == "user"), None)

    def connecting_path(self, source_id: str, target_id: str, *, max_hops: int = MAX_PATH_HOPS) -> list[Hop] | None:
        """Shortest path that says something: avoid the owner's node when a route
        exists without it, since nearly every pair is trivially linked through it."""
        owner = self.owner()
        if owner and owner.id not in (source_id, target_id):
            path = self.shortest_path(source_id, target_id, max_hops=max_hops, avoid={owner.id})
            if path is not None:
                return path
        return self.shortest_path(source_id, target_id, max_hops=max_hops)

    def hubs(self, limit: int = 8) -> list[GraphNode]:
        ranked = sorted(self.nodes, key=lambda n: (-self.degree(n.id), _norm(n.label)))
        return [n for n in ranked[:limit] if self.degree(n.id) > 0]

    # -- operations --------------------------------------------------------
    def hops(
        self,
        node_id: str,
        *,
        direction: Direction = "both",
        edge_types: set[str] | None = None,
        node_types: set[str] | None = None,
    ) -> list[Hop]:
        """Edges touching a node, optionally narrowed by direction and type."""
        out: list[Hop] = []
        for hop in self._hops.get(node_id, []):
            if direction == "out" and not hop.outgoing:
                continue
            if direction == "in" and hop.outgoing:
                continue
            if edge_types and hop.edge.type not in edge_types:
                continue
            if node_types and self._by_id[hop.other].type not in node_types:
                continue
            out.append(hop)
        return out

    def search(
        self, query: str, *, node_types: set[str] | None = None, limit: int = 10,
    ) -> list[tuple[GraphNode, float]]:
        """Rank nodes by how well their label (then properties) match the query.

        An empty query lists nodes of the requested types, best-connected first.
        """
        q = _norm(query)
        q_tokens = set(_tokens(query))
        scored: list[tuple[GraphNode, float]] = []
        for node in self.nodes:
            if node_types and node.type not in node_types:
                continue
            if not q:
                scored.append((node, 0.0))
                continue
            label = _norm(node.label)
            label_tokens = set(_tokens(node.label))
            if label == q:
                score = 1.0
            elif q in label:
                score = 0.85
            elif q_tokens and q_tokens <= label_tokens:
                score = 0.75
            else:
                prop_text = _norm(" ".join(str(v) for v in clean_properties(node.properties).values()))
                hay = label_tokens | set(_tokens(prop_text))
                overlap = len(q_tokens & hay) / len(q_tokens) if q_tokens else 0.0
                score = 0.6 * overlap if overlap else (0.4 if q in prop_text else 0.0)
            if score > 0:
                scored.append((node, round(score, 2)))
        scored.sort(key=lambda pair: (-pair[1], -self.degree(pair[0].id), _norm(pair[0].label)))
        return scored[: max(1, limit)]

    def traverse(
        self,
        start_id: str,
        *,
        depth: int = 1,
        direction: Direction = "both",
        edge_types: set[str] | None = None,
        node_types: set[str] | None = None,
        limit: int = 40,
    ) -> tuple[list[tuple[GraphNode, int, Hop]], int]:
        """Breadth-first walk out from a node.

        `node_types` filters what is *returned*; the walk itself still passes
        through other node types, so "pets within 2 hops" finds pets reached via
        a person. Returns (reached nodes with hop distance and the edge that
        reached them, how many more were cut off by `limit`).
        """
        if start_id not in self._by_id:
            return [], 0
        depth = max(1, min(depth, MAX_DEPTH))
        seen = {start_id}
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        found: list[tuple[GraphNode, int, Hop]] = []
        while queue:
            current, dist = queue.popleft()
            if dist >= depth:
                continue
            for hop in self.hops(current, direction=direction, edge_types=edge_types):
                if hop.other in seen:
                    continue
                seen.add(hop.other)
                queue.append((hop.other, dist + 1))
                other = self._by_id[hop.other]
                if not node_types or other.type in node_types:
                    found.append((other, dist + 1, hop))
        return found[:limit], max(0, len(found) - limit)

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
        *,
        edge_types: set[str] | None = None,
        max_hops: int = MAX_PATH_HOPS,
        avoid: set[str] | None = None,
    ) -> list[Hop] | None:
        """Fewest-edges path ignoring edge direction, or None when unconnected.

        `avoid` lists nodes the path may not pass through (endpoints are exempt).
        """
        if source_id not in self._by_id or target_id not in self._by_id:
            return None
        if source_id == target_id:
            return []
        max_hops = max(1, min(max_hops, MAX_PATH_HOPS))
        came_from: dict[str, tuple[str, Hop] | None] = {source_id: None}
        queue: deque[tuple[str, int]] = deque([(source_id, 0)])
        while queue:
            current, dist = queue.popleft()
            if dist >= max_hops:
                continue
            for hop in self.hops(current, edge_types=edge_types):
                if hop.other in came_from or (avoid and hop.other in avoid and hop.other != target_id):
                    continue
                came_from[hop.other] = (current, hop)
                if hop.other == target_id:
                    path: list[Hop] = []
                    cursor = target_id
                    while (step := came_from[cursor]) is not None:
                        cursor, taken = step
                        path.append(taken)
                    return list(reversed(path))
                queue.append((hop.other, dist + 1))
        return None

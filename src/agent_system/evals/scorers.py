"""Deterministic scorers. Each returns a Score or None when the case doesn't assert it.

Scores are 0..1; `passed` is the gate. `tag` names the failure category used
by the failure analysis and the case filter in the Evals tab.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_system.evals.schema import EvalCase, ResearchCase


@dataclass
class Score:
    name: str
    score: float
    passed: bool
    tag: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())


def _as_list(v: str | list[str] | None) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(n == h for h in it) for n in needle)


# ---------------------------------------------------------------------------
# Agent-turn scorers (operate on the LAST turn's trace dict)
# ---------------------------------------------------------------------------


def detected_intent(trace: dict[str, Any]) -> str | None:
    for d in trace.get("decisions", []):
        if d["node"] == "AnalyzeIntent":
            return d["inputs"].get("intent")
    return None


def tools_used(trace: dict[str, Any]) -> list[str]:
    return [t["tool"] for t in trace.get("tool_calls", [])]


def score_intent(case: EvalCase, trace: dict[str, Any]) -> Score | None:
    want = _as_list(case.expect.intent)
    if not want:
        return None
    got = detected_intent(trace)
    ok = got in want
    return Score("intent", 1.0 if ok else 0.0, ok, "wrong_intent", {"expected": want, "actual": got})


def score_route(case: EvalCase, trace: dict[str, Any]) -> Score | None:
    want = case.expect.route
    forbid = case.expect.forbid_nodes
    if not want and not forbid:
        return None
    path = trace.get("path", [])
    ok_order = True
    if want:
        ok_order = path == want if case.expect.route_exact else is_subsequence(want, path)
    hit_forbidden = [n for n in forbid if n in path]
    ok = ok_order and not hit_forbidden
    matched = sum(1 for n in (want or []) if n in path)
    score = (matched / len(want)) if want else 1.0
    if hit_forbidden:
        score *= 0.5
    return Score("route", 1.0 if ok else round(score, 3), ok, "wrong_route",
                 {"expected": want, "actual": path, "forbidden_hit": hit_forbidden, "exact": case.expect.route_exact})


def score_tool(case: EvalCase, trace: dict[str, Any]) -> Score | None:
    want = _as_list(case.expect.tool)
    if not want:
        return None
    used = tools_used(trace)
    ok = not used if want == ["none"] else any(t in want for t in used)
    return Score("tool", 1.0 if ok else 0.0, ok, "wrong_tool", {"expected": want, "actual": used})


def score_tool_args(case: EvalCase, trace: dict[str, Any]) -> Score | None:
    want = case.expect.tool_args
    if not want:
        return None
    calls = trace.get("tool_calls", [])
    target = _as_list(case.expect.tool)
    call = next((c for c in calls if not target or c["tool"] in target), calls[0] if calls else None)
    if call is None:
        return Score("tool_args", 0.0, False, "bad_args", {"expected": want, "actual": None})
    misses = {k: v for k, v in want.items() if _norm(v) not in _norm(call["arguments"].get(k))}
    score = 1 - len(misses) / len(want)
    return Score("tool_args", round(score, 3), not misses, "bad_args",
                 {"expected": want, "actual": call["arguments"], "missing": misses})


def _retrieved_texts(trace: dict[str, Any]) -> list[tuple[str, int, str, bool]]:
    """(source, rank, text, used_in_prompt) for every retrieval hit."""
    out = []
    for r in trace.get("retrievals", []):
        for rank, h in enumerate(r.get("hits", []), start=1):
            text = " ".join(str(h.get(k) or "") for k in ("name", "content", "type"))
            used = h.get("used_in_prompt", r["source"].startswith("tool:"))
            out.append((r["source"], rank, text, bool(used)))
    for t in trace.get("tool_calls", []):  # tool output is what the model actually saw
        out.append((f"tool_result:{t['tool']}", 1, str(t.get("result") or ""), True))
    return out


def score_recall(case: EvalCase, trace: dict[str, Any], k: int = 5) -> Score | None:
    facts = case.expect.must_recall
    if not facts:
        return None
    texts = _retrieved_texts(trace)
    per_fact = {}
    rr = []
    for fact in facts:
        f = _norm(fact)
        matches = [(src, rank, used) for src, rank, text, used in texts if f in _norm(text)]
        best = min((rank for _, rank, _ in matches), default=None)
        per_fact[fact] = {
            "retrieved": bool(matches),
            "in_context": any(used for _, _, used in matches),
            "best_rank": best,
            "sources": sorted({src for src, _, _ in matches}),
        }
        rr.append(1.0 / best if best else 0.0)
    in_ctx = sum(1 for v in per_fact.values() if v["in_context"]) / len(facts)
    at_k = sum(1 for v in per_fact.values() if v["best_rank"] and v["best_rank"] <= k) / len(facts)
    return Score("recall", round(in_ctx, 3), in_ctx == 1.0, "missed_retrieval",
                 {"recall_in_context": round(in_ctx, 3), f"recall@{k}": round(at_k, 3),
                  "mrr": round(sum(rr) / len(rr), 3), "facts": per_fact})


def score_mentions(case: EvalCase, response: str) -> list[Score]:
    out = []
    r = _norm(response)
    if case.expect.must_mention:
        missing = [m for m in case.expect.must_mention if _norm(m) not in r]
        n = len(case.expect.must_mention)
        out.append(Score("mentions", round(1 - len(missing) / n, 3), not missing, "incomplete_answer",
                         {"missing": missing}))
    if case.expect.must_not_mention:
        leaked = [m for m in case.expect.must_not_mention if _norm(m) in r]
        out.append(Score("no_hallucination", 0.0 if leaked else 1.0, not leaked, "hallucinated_memory",
                         {"leaked": leaked}))
    return out


def _entity_keys(node: dict[str, Any]) -> set[str]:
    return {_norm(node.get("name"))} | {_norm(a) for a in node.get("aliases") or []}


def score_entities(case: EvalCase, snapshot: dict[str, list[dict[str, Any]]]) -> list[Score]:
    want = case.expect.entities
    out: list[Score] = []
    if case.expect.forbid_entities:
        forbidden = {_norm(n) for n in case.expect.forbid_entities}
        created = [n.get("name") for t in ("person", "pet", "location") for n in snapshot.get(t, [])
                   if _entity_keys(n) & forbidden]
        out.append(Score("no_spurious_entities", 0.0 if created else 1.0, not created, "entity_spurious",
                         {"created": created}))
    if not want:
        return out
    found = 0
    details = []
    dup_names = []
    for e in want:
        nodes = snapshot.get(e.type, [])
        names = {_norm(e.name)} | {_norm(a) for a in e.aliases}
        match = [n for n in nodes if _norm(n.get("name")) == _norm(e.name)]
        # every node that answers to this entity's name or aliases; >1 means it was split
        claimants = [n for n in nodes if _entity_keys(n) & names]
        node = match[0] if match else None
        problems = []
        if node is None:
            problems.append("missing")
        else:
            unresolved = [a for a in e.aliases if _norm(a) not in _entity_keys(node)]
            if unresolved:
                problems.append(f"aliases not linked: {unresolved}")
            if e.relationship_type and _norm(node.get("relationship_type")) != _norm(e.relationship_type):
                problems.append(f"relationship {node.get('relationship_type')!r} ≠ {e.relationship_type!r}")
            if e.species and _norm(node.get("species")) != _norm(e.species):
                problems.append(f"species {node.get('species')!r} ≠ {e.species!r}")
        if len(claimants) > 1:
            dup_names.append(e.name)
            problems.append(f"split across {[c.get('name') for c in claimants]}")
        if node is not None and not problems:
            found += 1
        details.append({"entity": e.name, "type": e.type, "ok": not problems, "problems": problems})
    recall = found / len(want)
    expected_names = {_norm(n) for e in want for n in [e.name, *e.aliases]}
    extra = [n.get("name") for t in ("person", "pet", "location") for n in snapshot.get(t, [])
             if not (_entity_keys(n) & expected_names)]
    out.append(Score("entity_resolution", round(recall, 3), recall == 1.0, "entity_miss",
                     {"entities": details, "unexpected_entities": extra}))
    if case.expect.no_duplicate_entities:
        out.append(Score("entity_dedup", 0.0 if dup_names else 1.0, not dup_names, "entity_dup",
                         {"duplicated": dup_names}))
    return out


def score_latency(case: EvalCase, trace: dict[str, Any]) -> Score | None:
    limit = case.expect.max_latency_ms
    if not limit:
        return None
    ms = trace.get("total_ms") or 0.0
    return Score("latency", 1.0 if ms <= limit else round(limit / ms, 3), ms <= limit, "slow",
                 {"total_ms": ms, "limit_ms": limit})


def score_agent_case(
    case: EvalCase, trace: dict[str, Any], response: str, snapshot: dict[str, list[dict[str, Any]]] | None,
) -> list[Score]:
    scores: list[Score | None] = [
        score_intent(case, trace),
        score_route(case, trace),
        score_tool(case, trace),
        score_tool_args(case, trace),
        score_recall(case, trace),
        score_latency(case, trace),
    ]
    out = [s for s in scores if s is not None]
    out += score_mentions(case, response)
    if snapshot is not None:
        out += score_entities(case, snapshot)
    return out


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


def score_research_sources(case: ResearchCase, sources: list[dict[str, Any]], lanes_with_findings: list[str]) -> list[Score]:
    n = len(sources)
    domains = {(_norm(s.get("url")).split("/")[2] if "://" in (s.get("url") or "") else s.get("kind", "?"))
               for s in sources}
    diversity = len(domains) / n if n else 0.0
    missing_lanes = [lane for lane in case.expect_lanes if lane not in lanes_with_findings]
    with_url = sum(1 for s in sources if s.get("url"))
    return [
        Score("source_count", min(n / case.min_sources, 1.0), n >= case.min_sources, "thin_sources",
              {"sources": n, "min": case.min_sources}),
        Score("source_diversity", round(diversity, 3), diversity >= 0.5, "low_diversity",
              {"distinct_domains": len(domains), "sources": n}),
        Score("lane_coverage", round(1 - len(missing_lanes) / max(len(case.expect_lanes), 1), 3),
              not missing_lanes, "lane_empty", {"missing": missing_lanes}),
        Score("citable_sources", round(with_url / n, 3) if n else 0.0, n > 0 and with_url == n, "uncitable_source",
              {"with_url": with_url, "sources": n}),
    ]


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    idx = (len(vals) - 1) * p
    lo, hi = int(idx), min(int(idx) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo), 1)

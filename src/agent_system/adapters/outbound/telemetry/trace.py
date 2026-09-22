"""Per-turn trace capture: node spans, branch decisions, retrievals, tool I/O,
LLM usage and cost.

A TurnTrace is bound to the current asyncio context with `bind_trace()`. FSM
nodes write to it through AgentDependencies; LLM calls are captured without
touching call sites by an OpenTelemetry span processor fed by pydantic-ai's
instrumentation (see `install_llm_capture`). The serialized form (`to_dict`)
is what `turn_traces.trace` and `eval_case_results.trace` store, and what the
predicate-tree viewer renders.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

TRACE_VERSION = 1
_MAX_TEXT = 4000

_current_trace: contextvars.ContextVar[TurnTrace | None] = contextvars.ContextVar(
    "current_turn_trace", default=None
)
_current_node: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_fsm_node", default=None
)


def _clip(value: Any, limit: int = _MAX_TEXT) -> Any:
    """JSON-safe, size-bounded copy of an arbitrary value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {str(k): _clip(v, limit) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in list(value)[:50]]
    return _clip(str(value), limit)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


@lru_cache
def _configured_prices() -> dict[str, dict[str, float]]:
    from agent_system.composition_root.config import get_settings

    try:
        raw = json.loads(get_settings().model_pricing_json or "{}")
        return {str(k): {kk: float(vv) for kk, vv in v.items()} for k, v in raw.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("MODEL_PRICING_JSON is not valid JSON: %s", exc)
        return {}


def _bare_model(model: str) -> str:
    return model.split(":", 1)[1] if ":" in model else model


def price_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float | None:
    """USD cost of one call, or None when the model has no known price.

    MODEL_PRICING_JSON wins (it is how unreleased/private models get priced);
    otherwise genai-prices is consulted.
    """
    name = _bare_model(model)
    table = _configured_prices()
    rates = table.get(name) or next((v for k, v in table.items() if name.startswith(k)), None)
    if rates:
        uncached = max(input_tokens - cached_tokens, 0)
        cached_rate = rates.get("cached_input", rates.get("input", 0.0))
        return (
            uncached * rates.get("input", 0.0)
            + cached_tokens * cached_rate
            + output_tokens * rates.get("output", 0.0)
        ) / 1_000_000
    try:
        from genai_prices import Usage, calc_price

        calc = calc_price(
            Usage(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cached_tokens or None),
            model_ref=name,
            provider_id="openai",
        )
        return float(calc.total_price)
    except Exception:  # noqa: BLE001 - unknown model is the common case
        return None


# ---------------------------------------------------------------------------
# Trace records
# ---------------------------------------------------------------------------


@dataclass
class NodeSpan:
    node: str
    seq: int
    start_ms: float
    end_ms: float | None = None

    @property
    def duration_ms(self) -> float | None:
        return None if self.end_ms is None else round(self.end_ms - self.start_ms, 1)


@dataclass
class LLMCall:
    node: str | None
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    duration_ms: float
    cost_usd: float | None
    at_ms: float
    input_preview: str | None = None
    output_preview: str | None = None
    role: str = "system"  # "system" = system under test, "judge" = eval judge


@dataclass
class TurnTrace:
    """Everything observable about one agent turn."""

    user_input: str = ""
    started_at: float = field(default_factory=time.time)
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    spans: list[NodeSpan] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    retrievals: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    embedding_calls: list[dict[str, Any]] = field(default_factory=list)
    response: str | None = None
    error: str | None = None
    total_ms: float | None = None

    # -- clock ------------------------------------------------------------
    def now_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)

    # -- spans ------------------------------------------------------------
    def enter_node(self, node: str) -> None:
        self.exit_node()
        self.spans.append(NodeSpan(node=node, seq=len(self.spans), start_ms=self.now_ms()))

    def exit_node(self) -> None:
        if self.spans and self.spans[-1].end_ms is None:
            self.spans[-1].end_ms = self.now_ms()

    def finish(self, response: str | None = None, error: str | None = None) -> None:
        self.exit_node()
        self.total_ms = self.now_ms()
        if response is not None:
            self.response = response
        if error is not None:
            self.error = error

    @property
    def current_seq(self) -> int | None:
        return self.spans[-1].seq if self.spans else None

    # -- records ----------------------------------------------------------
    def add_event(self, event_type: str, node: str, message: str, data: dict | None) -> None:
        if event_type == "response_chunk":
            return  # streaming deltas carry no structure; the final response is kept
        self.events.append({
            "t_ms": self.now_ms(), "seq": self.current_seq, "type": event_type,
            "node": node, "message": _clip(message, 500), "data": _clip(data or {}),
        })

    def add_decision(
        self, node: str, predicate: str, result: bool, next_node: str, inputs: dict[str, Any] | None = None,
    ) -> None:
        self.decisions.append({
            "t_ms": self.now_ms(), "seq": self.current_seq, "node": node,
            "predicate": predicate, "result": bool(result), "next": next_node,
            "inputs": _clip(inputs or {}, 300),
        })

    def add_retrieval(self, source: str, query: str, hits: list[dict[str, Any]], **params: Any) -> None:
        self.retrievals.append({
            "t_ms": self.now_ms(), "seq": self.current_seq, "node": _current_node.get(),
            "source": source, "query": _clip(query, 500), "params": _clip(params),
            "hits": [_clip(h, 600) for h in hits[:25]],
        })

    def add_tool_call(self, tool: str, arguments: dict[str, Any], result: str | None, success: bool, duration_ms: float) -> None:
        self.tool_calls.append({
            "t_ms": self.now_ms(), "seq": self.current_seq, "tool": tool,
            "arguments": _clip(arguments, 500), "result": _clip(result),
            "success": success, "duration_ms": round(duration_ms, 1),
        })

    def add_llm_call(self, call: LLMCall) -> None:
        self.llm_calls.append(call)

    def add_embedding_call(self, model: str, tokens: int, duration_ms: float) -> None:
        self.embedding_calls.append({
            "t_ms": self.now_ms(), "node": _current_node.get(), "model": model, "tokens": tokens,
            "duration_ms": round(duration_ms, 1), "cost_usd": price_usd(model, tokens, 0),
        })

    # -- rollups ----------------------------------------------------------
    def usage(self, role: str = "system") -> dict[str, Any]:
        calls = [c for c in self.llm_calls if c.role == role]
        costs = [c.cost_usd for c in calls]
        emb_costs = [e["cost_usd"] for e in self.embedding_calls] if role == "system" else []
        all_costs = costs + emb_costs
        known = [c for c in all_costs if c is not None]
        return {
            "llm_calls": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "cached_tokens": sum(c.cached_tokens for c in calls),
            "embedding_tokens": sum(e["tokens"] for e in self.embedding_calls) if role == "system" else 0,
            "cost_usd": round(sum(known), 6) if known else None,
            "unpriced_calls": sum(1 for c in all_costs if c is None),
        }

    def path(self) -> list[str]:
        return [s.node for s in self.spans]

    def to_dict(self) -> dict[str, Any]:
        per_node: dict[int, dict[str, Any]] = {}
        for c in self.llm_calls:
            if c.role != "system":
                continue
            seq = next((s.seq for s in reversed(self.spans) if s.node == c.node and s.start_ms <= c.at_ms), None)
            if seq is None:
                continue
            agg = per_node.setdefault(seq, {"input_tokens": 0, "output_tokens": 0, "llm_ms": 0.0, "cost_usd": 0.0})
            agg["input_tokens"] += c.input_tokens
            agg["output_tokens"] += c.output_tokens
            agg["llm_ms"] += c.duration_ms
            agg["cost_usd"] += c.cost_usd or 0.0
        return {
            "version": TRACE_VERSION,
            "user_input": _clip(self.user_input),
            "started_at": self.started_at,
            "total_ms": self.total_ms,
            "path": self.path(),
            "spans": [
                {**asdict(s), "duration_ms": s.duration_ms, **per_node.get(s.seq, {})} for s in self.spans
            ],
            "decisions": self.decisions,
            "events": self.events,
            "retrievals": self.retrievals,
            "tool_calls": self.tool_calls,
            "llm_calls": [asdict(c) for c in self.llm_calls],
            "embedding_calls": self.embedding_calls,
            "usage": self.usage("system"),
            "judge_usage": self.usage("judge"),
            "response": _clip(self.response, 20000),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Context binding
# ---------------------------------------------------------------------------


def current_trace() -> TurnTrace | None:
    return _current_trace.get()


@contextmanager
def bind_trace(trace: TurnTrace | None) -> Iterator[TurnTrace | None]:
    token = _current_trace.set(trace)
    try:
        yield trace
    finally:
        _current_trace.reset(token)


@contextmanager
def llm_role(role: str) -> Iterator[None]:
    """Tag LLM calls inside the block (e.g. "judge") so they aren't billed to the system under test."""
    token = _current_role.set(role)
    try:
        yield
    finally:
        _current_role.reset(token)


_current_role: contextvars.ContextVar[str] = contextvars.ContextVar("llm_role", default="system")


def set_current_node(node: str | None) -> contextvars.Token:
    return _current_node.set(node)


# ---------------------------------------------------------------------------
# LLM capture via pydantic-ai OpenTelemetry instrumentation
# ---------------------------------------------------------------------------


class _TraceSpanProcessor:
    """Turns pydantic-ai `chat <model>` spans into LLMCall records on the bound TurnTrace.

    on_end runs synchronously in the context that closed the span, so the
    contextvars bound by the FSM runner (trace, node, role) are visible.
    """

    def __init__(self) -> None:
        self._agent_names: dict[int, str] = {}

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        attrs = span.attributes or {}
        name = attrs.get("gen_ai.agent.name") or attrs.get("agent_name")
        if name:
            self._agent_names[span.context.span_id] = str(name)

    def on_end(self, span: Any) -> None:
        attrs = span.attributes or {}
        if attrs.get("gen_ai.agent.name") or attrs.get("agent_name"):
            self._agent_names.pop(span.context.span_id, None)
            return
        if attrs.get("gen_ai.operation.name") != "chat":
            return
        trace = _current_trace.get()
        if trace is None:
            return
        try:
            model = str(attrs.get("gen_ai.response.model") or attrs.get("gen_ai.request.model") or "unknown")
            input_tokens = int(attrs.get("gen_ai.usage.input_tokens") or 0)
            output_tokens = int(attrs.get("gen_ai.usage.output_tokens") or 0)
            cached = int(attrs.get("gen_ai.usage.details.cache_read_tokens") or 0)
            duration_ms = (span.end_time - span.start_time) / 1e6 if span.end_time else 0.0
            cost = price_usd(model, input_tokens, output_tokens, cached)
            if cost is None and attrs.get("operation.cost") is not None:
                cost = float(attrs["operation.cost"])
            parent = span.parent.span_id if span.parent else None
            trace.add_llm_call(LLMCall(
                node=_current_node.get(),
                agent=self._agent_names.get(parent, "agent") if parent else "agent",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached,
                duration_ms=round(duration_ms, 1),
                cost_usd=cost,
                at_ms=max(trace.now_ms() - duration_ms, 0.0),
                input_preview=_last_user_text(attrs.get("gen_ai.input.messages")),
                output_preview=_output_text(attrs.get("gen_ai.output.messages")),
                role=_current_role.get(),
            ))
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a turn
            logger.debug("LLM span capture failed: %s", exc)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _parts_text(parts: list[dict[str, Any]]) -> str:
    out = []
    for p in parts:
        if p.get("type") == "text":
            out.append(str(p.get("content", "")))
        elif p.get("type") == "tool_call":
            out.append(json.dumps(p.get("arguments", {}))[:_MAX_TEXT])
    return "\n".join(out)


def _last_user_text(raw: Any) -> str | None:
    try:
        msgs = json.loads(raw) if isinstance(raw, str) else raw
        for m in reversed(msgs or []):
            if m.get("role") == "user":
                return _clip(_parts_text(m.get("parts", [])))
    except Exception:  # noqa: BLE001
        pass
    return None


def _output_text(raw: Any) -> str | None:
    try:
        msgs = json.loads(raw) if isinstance(raw, str) else raw
        return _clip("\n".join(_parts_text(m.get("parts", [])) for m in msgs or []))
    except Exception:  # noqa: BLE001
        return None


_installed = False


def install_llm_capture() -> None:
    """Instrument every pydantic-ai Agent with a private tracer provider whose
    only processor records into the bound TurnTrace. Idempotent; spans are not
    exported anywhere."""
    global _installed
    if _installed:
        return
    from opentelemetry.sdk.trace import TracerProvider
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings

    provider = TracerProvider()
    provider.add_span_processor(_TraceSpanProcessor())  # type: ignore[arg-type]
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, include_binary_content=False, version=2))
    _installed = True

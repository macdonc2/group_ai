"""OpenTelemetry export: traces and metrics over OTLP to a Collector.

Off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set, so tests, evals and a bare
laptop run exactly as before. When on:

* one trace per request: the HTTP server span, each SQL statement, each
  outbound HTTP call, and pydantic-ai's agent / model / tool spans, all
  parented correctly because they share one tracer provider;
* metrics: request rate / errors / duration from the FastAPI instrumentation,
  token and cost histograms from pydantic-ai, and a count of agent turns by
  outcome;
* logs are *not* sent over OTLP. They stay JSON on stdout (collected by the
  cluster's log agent) and carry `trace_id`, which is what links a log line
  to its trace.

The app knows only "an OTLP endpoint". What happens next (sampling, removing
prompt text, which backend) is the Collector's job, so it can change without
a deploy of this service.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_NAME = "agent-system-backend"
_state: dict[str, Any] = {"enabled": False, "turns": None}


def telemetry_enabled() -> bool:
    return bool(_state["enabled"])


def setup_telemetry(app: Any, *, endpoint: str | None, environment: str) -> bool:
    """Wire exporters and instrument the app. Returns whether export is on."""
    if not endpoint:
        return False
    if _state["enabled"]:  # a second app in the same process (tests) reuses the providers
        _instrument_app(app)
        return True

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from agent_system.adapters.outbound.telemetry.trace import install_llm_capture, tracer_provider

    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": os.environ.get("GIT_SHA") or "dev",
        "deployment.environment.name": environment,
    })
    base = endpoint.rstrip("/")

    # Traces: the provider the LLM capture already uses, so agent spans join
    # the request's trace instead of living in a private one.
    provider = tracer_provider(resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces")))
    trace.set_tracer_provider(provider)

    # Metrics: pushed every 30 s; the Collector exposes them to Prometheus.
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{base}/v1/metrics"), export_interval_millis=30_000,
        )],
    )
    metrics.set_meter_provider(meter_provider)
    _state["turns"] = metrics.get_meter(SERVICE_NAME).create_counter(
        "agent.turns", unit="{turn}", description="Agent turns completed, by source and outcome",
    )

    install_llm_capture(meter_provider=meter_provider)

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()
    _state["enabled"] = True
    _instrument_app(app)
    logger.info("OpenTelemetry export on", extra={"event": "telemetry_enabled", "endpoint": base})
    return True


def _instrument_app(app: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    # Probes would otherwise be most of the traces.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")


def instrument_database(engine: Any) -> None:
    """Trace SQL statements on this engine (call once it exists)."""
    if not _state["enabled"]:
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))


def record_turn(source: str, outcome: str) -> None:
    """Count one finished agent turn. `outcome` is a small fixed vocabulary
    (ok, error, step_limit, timeout): low cardinality, so safe as a label."""
    counter = _state["turns"]
    if counter is not None:
        counter.add(1, {"source": source, "outcome": outcome})


def annotate_current_span(**attributes: Any) -> None:
    """Put request-scoped facts (request ID, user ID) on the active span."""
    if not _state["enabled"]:
        return
    from opentelemetry import trace

    span = trace.get_current_span()
    if span.is_recording():
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)


def current_trace_ids() -> tuple[str, str] | None:
    """(trace_id, span_id) of the active span as hex, for log correlation."""
    if not _state["enabled"]:
        return None
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"


def shutdown_telemetry() -> None:
    """Flush what is buffered so the last requests before a restart aren't lost."""
    if not _state["enabled"]:
        return
    from opentelemetry import metrics, trace

    for provider in (trace.get_tracer_provider(), metrics.get_meter_provider()):
        try:
            provider.shutdown()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("telemetry shutdown: %s", exc)

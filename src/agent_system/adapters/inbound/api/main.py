"""FastAPI application factory."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from agent_system.adapters.inbound.api.dependencies import get_database, set_database
from agent_system.adapters.inbound.api.security_headers import SecurityHeadersMiddleware
from agent_system.adapters.inbound.api.observability import (
    RequestContextMiddleware,
    configure_logging,
)
from agent_system.adapters.inbound.api.routes import (
    agent_router,
    auth_router,
    calendar_router,
    conversations_router,
    evals_router,
    groups_router,
    journal_router,
    knowledge_router,
    plans_router,
    recipes_router,
    research_router,
    tools_router,
)
from agent_system.adapters.outbound.telemetry.otel import instrument_database, setup_telemetry, shutdown_telemetry
from agent_system.adapters.outbound.research.runner import (
    ResearchRunner,
    ResearchSettings,
    mark_interrupted_on_startup,
    set_runner,
)
from agent_system.composition_root.config import Settings, get_settings, secret_key_problem
from agent_system.composition_root.container import Container, set_container

logger = logging.getLogger(__name__)


def _deployed(settings: Settings) -> bool:
    return settings.app_env.lower() == "production" or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


async def _check(name: str, probe: Any, timeout_s: float = 2.0) -> str:
    """Run one dependency probe with a deadline; never raises."""
    import asyncio

    try:
        await asyncio.wait_for(probe(), timeout_s)
        return "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means "down"
        logger.warning("Readiness check failed: %s (%s)", name, type(exc).__name__, extra={"event": "dependency_down", "dependency": name})
        return "down"


# Load environment variables from .env file
# This ensures OPENAI_API_KEY is available for PydanticAI
load_dotenv()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.
    
    Args:
        settings: Application settings. If None, loads from environment.
        
    Returns:
        Configured FastAPI application
    """
    settings = settings or get_settings()
    configure_logging(
        as_json=settings.log_format == "json" or (settings.log_format == "auto" and _deployed(settings))
    )
    
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan handler."""
        # Tokens are signed and checked with this app's key; stored API keys are
        # still encrypted with the process-wide one (`get_api_key_encryption` in `composition_root/config.py`),
        # so both are judged. Fatal where real users are, a warning on a laptop.
        problem = secret_key_problem(settings.secret_key) or secret_key_problem(get_settings().secret_key)
        if problem:
            if _deployed(settings):
                raise RuntimeError(f"Refusing to start: {problem}. Set a random SECRET_KEY of 32+ characters.")
            logging.getLogger("agent_system").warning("%s; fine for local development only.", problem)

        # The one place the long-lived objects are built: the database, the graph store,
        # the embedding and calendar adapters. Registered so code that still calls
        # `get_container()` gets these same objects rather than building a second set.
        container = await Container.create(settings)
        set_container(container)
        app.state.container = container
        db = container.database
        set_database(db)
        instrument_database(db.engine)

        # Deep Research runs in-process; anything mid-flight at the last
        # shutdown is gone, so say so on those rows and start a fresh runner.
        await mark_interrupted_on_startup(db)
        from agent_system.adapters.outbound.persistence.trace_repository import mark_orphaned_eval_runs
        await mark_orphaned_eval_runs(db)
        set_runner(ResearchRunner(db, ResearchSettings(
            strong_model=settings.default_model,
            fast_model=settings.fallback_model,
            tts_model=settings.tts_model,
            tts_voice=settings.tts_voice,
            semantic_scholar_key=settings.semantic_scholar_api_key,
            github_token=settings.github_token,
        )))
        
        yield
        
        # Cleanup: closes the database pool and the graph driver
        shutdown_telemetry()
        set_container(None)
        app.state.container = None
        await container.close()
    
    # The interactive docs describe every endpoint and parameter. Useful on a
    # laptop; on the public site they are a map for anyone probing it.
    docs_on = settings.enable_api_docs if settings.enable_api_docs is not None else not _deployed(settings)
    app = FastAPI(
        title="Agent System API",
        description="Hexagonal architecture agentic reasoning system with PydanticAI",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    # Routes and dependencies read configuration from here (`SettingsDep`).
    app.state.settings = settings

    # CORS decides which *other* websites' pages may call this API from a
    # browser. Deployed, the frontend is served from the same origin, so the
    # answer is none and no CORS headers are sent at all. Locally the Vite dev
    # server is a different origin. Credentials are never allowed: auth is a
    # bearer token the page adds itself, not a cookie the browser attaches.
    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    if not origins and not _deployed(settings):
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Tracing and metrics, when a Collector endpoint is configured. Set up
    # before our own middleware is added so that middleware sits outside it.
    setup_telemetry(app, endpoint=settings.otel_exporter_otlp_endpoint, environment=settings.app_env)

    # Outermost of our middleware: every request, including ones CORS answers
    # itself, gets an ID and an access-log line.
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        """Give the caller the request ID to quote instead of a bare
        "Internal Server Error". The traceback is logged by the middleware."""
        request_id = request.scope.get("request_id")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
            headers={"X-Request-ID": request_id} if request_id else None,
        )

    # Include routers
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(calendar_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(evals_router, prefix="/api/v1")
    app.include_router(groups_router, prefix="/api/v1")
    app.include_router(journal_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(recipes_router, prefix="/api/v1")
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(tools_router, prefix="/api/v1")
    
    @app.get("/health/research")
    async def research_health() -> dict[str, Any]:
        """How many research jobs this process is running right now.

        No auth and no job details: the deploy guard polls it so a rollout
        never restarts the pod under a live run.
        """
        from agent_system.adapters.outbound.research.runner import get_runner

        try:
            runner = get_runner()
            active = sum(1 for live in runner._jobs.values() if not live.done)
        except RuntimeError:
            active = 0
        return {"active_research_jobs": active}

    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Liveness: the process is up and answering. Deliberately checks
        nothing else, because failing it makes Kubernetes restart the pod, and
        a restart does not fix a database that is down."""
        return {"status": "healthy", "version": "0.1.0"}

    @app.get("/health/ready")
    async def readiness(response: Response) -> dict[str, Any]:
        """Readiness: can this pod do useful work right now?

        The SQL database is required (no login without it), so its failure
        returns 503 and takes the pod out of rotation. The graph store is
        reported but does not fail the check: chat degrades without it, and
        with a single replica, failing here would take the whole API down.
        """
        from sqlalchemy import text

        async def database() -> None:
            async with get_database().session() as session:
                await session.execute(text("SELECT 1"))

        checks = {"database": await _check("database", database)}

        graph = getattr(getattr(app.state, "container", None), "knowledge_graph_adapter", None)
        driver = getattr(graph, "_driver", None)
        checks["graph"] = await _check("graph", driver.verify_connectivity) if driver else "not_connected"

        ready = checks["database"] == "ok"
        if not ready:
            response.status_code = 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}
    
    @app.get("/health/alerts")
    async def alerts() -> dict[str, Any]:
        """Is the agent itself in trouble? Judged from the last hour of stored chat turns.

        Readiness cannot see chats failing, an empty model account or runaway spend, because
        the API still answers 200 through all of them. This always returns 200 with a status,
        so a monitor can tell "the app is down" (no answer) from "the app is up and alerting".

        No auth, like the other health endpoints, so the response carries alert codes and
        fixed descriptions only: no amounts, counts of users or text. The numbers go to the
        log as `alert_firing`. The result is cached for a minute so polling costs one query.
        """
        import time

        from agent_system.adapters.outbound.persistence.trace_repository import load_turn_stats
        from agent_system.application.services.alerts import Thresholds, evaluate

        cached = getattr(app.state, "alerts_cache", None)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        s = settings
        thresholds = Thresholds(failed_turns_min=s.alert_failed_turns_min, failed_share=s.alert_failed_share,
                                p95_ms=s.alert_p95_ms, spend_hour_usd=s.alert_spend_hour_usd,
                                spend_day_usd=s.alert_spend_day_usd)
        try:
            async with get_database().session() as session:
                stats, spend_day = await load_turn_stats(session, thresholds.window_minutes)
            found, turns = evaluate(stats, spend_day, thresholds), len(stats)
        except Exception as exc:  # noqa: BLE001 - the check itself failing is an alert, not a 500
            logger.warning("Alert check failed: %s", type(exc).__name__, extra={"event": "alert_check_failed"})
            return {"status": "alerting", "window_minutes": thresholds.window_minutes,
                    "alerts": [{"code": "check_failed", "summary": "The alert check could not read the turn records. Check the database."}]}
        for alert in found:
            logger.warning("Alert firing: %s", alert.code, extra={"event": "alert_firing", "alert": alert.code, **alert.detail})
        body = {"status": "alerting" if found else "ok", "window_minutes": thresholds.window_minutes,
                "had_traffic": turns > 0, "alerts": [{"code": a.code, "summary": a.summary} for a in found]}
        app.state.alerts_cache = (time.monotonic(), body)
        return body

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Root endpoint with API information."""
        return {"name": "Agent System API", "version": "0.1.0", "health": "/health"}
    
    return app


# Default application instance
app = create_app()

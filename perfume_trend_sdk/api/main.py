from __future__ import annotations

"""
PTI SDK Market Terminal — FastAPI application v1

Run:
    uvicorn perfume_trend_sdk.api.main:app --reload --port 8000

Or:
    python -m uvicorn perfume_trend_sdk.api.main:app --port 8000

Endpoints:
    GET    /api/v1/creators                          — creator leaderboard (influence_score)
    GET    /api/v1/creators/{creator_id}             — creator profile + entity portfolio
    GET    /api/v1/entities/{type}/{id}/creators     — top creators for a perfume/brand entity
    GET    /api/v1/dashboard                        — top movers + recent signals
    GET    /api/v1/screener                         — filterable entity table
    GET    /api/v1/entities                         — list all entities
    GET    /api/v1/entities/{entity_id}             — entity detail + chart series
    GET    /api/v1/signals                          — recent signal feed
    GET    /api/v1/watchlists                       — list watchlists
    POST   /api/v1/watchlists                       — create watchlist
    GET    /api/v1/watchlists/{id}                  — watchlist detail (enriched)
    POST   /api/v1/watchlists/{id}/items            — add entity to watchlist
    DELETE /api/v1/watchlists/{id}/items/{entity}   — remove entity
    GET    /api/v1/alerts                           — list alerts
    POST   /api/v1/alerts                           — create alert
    PATCH  /api/v1/alerts/{id}                      — update alert
    GET    /api/v1/alerts/history                   — alert event history
    GET    /health                                  — rich health check (db + env)
    GET    /healthz                                 — simple liveness probe
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from perfume_trend_sdk.api.routes import alerts, auth, catalog, creators, dashboard, emerging, entities, notes, signals, watchlists
from perfume_trend_sdk.db.market.session import _make_engine, get_database_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup probe — fail fast if DB is unreachable
# ---------------------------------------------------------------------------

def _probe_db() -> dict:
    """Connect to the DB and return diagnostic info. Raises on failure."""
    url = get_database_url()
    engine = _make_engine(url)
    dialect = engine.dialect.name  # 'sqlite' | 'postgresql'

    if dialect == "postgresql":
        safe_url = url.split("@")[-1] if "@" in url else url
        display = f"postgresql://{safe_url}"
    else:
        display = url.replace("sqlite:///", "sqlite:///")

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    logger.info("DB probe OK — %s (env=%s)", display, os.environ.get("PTI_ENV", "dev"))
    return {"dialect": dialect, "display": display}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: run startup checks before accepting traffic."""
    env = os.environ.get("PTI_ENV", "dev")
    logger.info("PTI Market Terminal starting — env=%s", env)

    # Fail fast: if the DB isn't reachable, crash now rather than at first request.
    try:
        db_info = _probe_db()
        app.state.db_dialect = db_info["dialect"]
        app.state.db_display = db_info["display"]
    except Exception as exc:
        logger.critical("Startup DB probe FAILED: %s", exc)
        raise

    yield  # application is running

    logger.info("PTI Market Terminal shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PTI SDK Market Terminal",
    description=(
        "Perfume Trend Intelligence Engine v1 — real-time trend market terminal "
        "for fragrance brands, retail buyers, and content strategists."
    ),
    version="1.0.3",  # Phase I3 — trend_state
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # V1 includes GET (read) + POST/PATCH/DELETE (watchlists + alerts mutations)
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────
app.include_router(creators.router, prefix="/api/v1/creators", tags=["creators"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
app.include_router(catalog.router, prefix="/api/v1/catalog", tags=["catalog"])
app.include_router(entities.router, prefix="/api/v1/entities", tags=["entities"])
app.include_router(notes.router, prefix="/api/v1", tags=["notes"])
app.include_router(signals.router, prefix="/api/v1/signals", tags=["signals"])
app.include_router(watchlists.router, prefix="/api/v1/watchlists", tags=["watchlists"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(emerging.router, prefix="/api/v1", tags=["emerging"])


# ── Health ────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"], summary="Rich health check")
def health_rich() -> dict:
    """Returns DB connectivity, dialect, and environment.

    Preferred by Railway / Render / Fly.io health checks.
    Returns 200 only if the DB is reachable.
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    env = os.environ.get("PTI_ENV", "dev")

    # Re-probe DB so the endpoint always reflects live state
    try:
        db_info = _probe_db()
        db_status = "connected"
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "db": "unreachable",
                "error": str(exc),
                "env": env,
            },
        )

    return {
        "status": "ok",
        "db": db_status,
        "db_dialect": db_info["dialect"],
        "env": env,
        "service": "pti-market-terminal",
        "version": "1.0.0",
    }


@app.get("/healthz", tags=["ops"], summary="Simple liveness probe")
def health_simple() -> dict:
    """Lightweight liveness check — does not probe the DB.

    Use /health for readiness; use /healthz for liveness.
    """
    return {"status": "ok"}

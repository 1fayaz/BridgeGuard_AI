"""FastAPI application factory.

Mounts routers and (in later tasks) middleware + the global exception handler.
Kept import-light so it starts without a database (Phase 1 is DB-independent).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.errors import register_exception_handlers
from api.routers import health, bridges


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await bridges.startup()
    yield
    # Shutdown
    await bridges.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BridgeGuard Backend API",
        version="0.1.0",
        description=(
            "Boundary between the BridgeGuard agent/skill pipeline and the "
            "outside world. All errors are structured; all writes are audited."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(bridges.router)
    return app


app = create_app()

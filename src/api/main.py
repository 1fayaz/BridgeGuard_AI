"""FastAPI application factory.

Mounts routers and (in later tasks) middleware + the global exception handler.
Kept import-light so it starts without a database (Phase 1 is DB-independent).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db.scope import close_pool, init_pool
from .errors import register_exception_handlers
from .routers import health, bridges


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    try:
        yield
    finally:
        await close_pool()


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

    # CORS for Vercel frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://bridgeguard.vercel.app",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()

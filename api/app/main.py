from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.ai.factory import create_agent_runtime, create_trace_manager
from api.app.ai.graph import AgentRuntime
from api.app.api.routes import ai, data, system
from api.app.core.config import Settings, get_settings
from api.app.core.errors import install_error_handlers
from api.app.core.logging import RequestLogMiddleware, configure_logging
from api.app.core.middleware import SelectiveGZipMiddleware
from api.app.db.pool import create_pool
from api.app.db.repository import PostgresRepository, Repository, UnavailableRepository
from api.app.db.sqlite_repository import SqliteRepository
from api.app.services.data import DataService


def create_app(
    *,
    settings: Settings | None = None,
    repository: Repository | None = None,
    agent_runtime: AgentRuntime | None = None,
) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(configured.log_level)
        pool = None
        active_repository = repository
        if active_repository is None and configured.database_url:
            pool = await create_pool(configured.database_url)
            active_repository = PostgresRepository(pool)
        if (
            active_repository is None
            and configured.local_sqlite_path is not None
            and configured.local_sqlite_path.exists()
        ):
            active_repository = SqliteRepository(configured.local_sqlite_path)
        if active_repository is None:
            active_repository = UnavailableRepository()
        app.state.settings = configured
        app.state.repository = active_repository
        app.state.data_service = DataService(
            active_repository,
            max_points=configured.max_points,
            cell_px=configured.cell_px,
            cluster_zoom=configured.cluster_zoom_threshold,
        )
        trace_manager = (
            agent_runtime.trace if agent_runtime is not None else create_trace_manager(configured)
        )
        app.state.trace_manager = trace_manager
        app.state.agent_runtime = agent_runtime or create_agent_runtime(
            configured,
            active_repository,
            trace_manager,
        )
        yield
        if pool is not None:
            await pool.close()

    app = FastAPI(title=configured.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024, compresslevel=5)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            configured.frontend_origin,
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        expose_headers=["X-Truncated", "X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(system.router)
    app.include_router(data.router)
    app.include_router(ai.router)
    return app


app = create_app()

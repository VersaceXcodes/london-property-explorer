from __future__ import annotations

from typing import cast

from fastapi import Request

from api.app.ai.graph import AgentRuntime
from api.app.ai.tracing import TraceManager
from api.app.core.config import Settings
from api.app.core.errors import AppError
from api.app.db.repository import Repository
from api.app.services.data import DataService


def get_repository(request: Request) -> Repository:
    return cast(Repository, request.app.state.repository)


def get_data_service(request: Request) -> DataService:
    return cast(DataService, request.app.state.data_service)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_agent_runtime(request: Request) -> AgentRuntime:
    runtime: AgentRuntime | None = request.app.state.agent_runtime
    if runtime is None:
        raise AppError(503, "AI_UNAVAILABLE", "The assistant is not configured")
    return runtime


def get_trace_manager(request: Request) -> TraceManager:
    return cast(TraceManager, request.app.state.trace_manager)

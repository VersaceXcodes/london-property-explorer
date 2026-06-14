from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api.app.ai.tracing import TraceManager
from api.app.api.dependencies import (
    get_app_settings,
    get_data_service,
    get_repository,
    get_trace_manager,
)
from api.app.core.config import Settings
from api.app.db.repository import Repository
from api.app.models import CapabilityResponse, HealthResponse, MetaResponse
from api.app.services.data import DataService

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(
    repository: Annotated[Repository, Depends(get_repository)], response: Response
) -> HealthResponse:
    await repository.health()
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse()


@router.get("/meta", response_model=MetaResponse)
async def meta(
    service: Annotated[DataService, Depends(get_data_service)], response: Response
) -> MetaResponse:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return MetaResponse.model_validate(await service.meta())


@router.get("/capabilities", response_model=CapabilityResponse)
async def capabilities(
    settings: Annotated[Settings, Depends(get_app_settings)],
    response: Response,
    trace: Annotated[TraceManager, Depends(get_trace_manager)],
) -> CapabilityResponse:
    response.headers["Cache-Control"] = "no-store"
    return CapabilityResponse(
        chat=settings.ai_enabled,
        rag=settings.ai_enabled and settings.rag_enabled,
        tracing=trace.enabled,
        streaming=settings.ai_enabled,
        feedback=trace.enabled,
        graph_version="lpe-agent-v1",
        corpus_version=settings.pinecone_namespace if settings.rag_enabled else None,
    )

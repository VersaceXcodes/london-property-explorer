from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from sse_starlette.sse import EventSourceResponse

from api.app.ai.graph import AgentRuntime
from api.app.ai.tracing import TraceManager
from api.app.api.dependencies import get_agent_runtime, get_trace_manager
from api.app.core.errors import AppError
from api.app.core.rate_limit import SlidingWindowRateLimiter
from api.app.models import ChatRequest, ChatResponse, FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api", tags=["assistant"])
limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60)


async def enforce_chat_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    if not await limiter.allow(client_key):
        raise AppError(429, "RATE_LIMITED", "Chat is limited to 10 requests per minute")


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_chat_limit)])
async def chat(
    body: ChatRequest,
    response: Response,
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> ChatResponse:
    response.headers["Cache-Control"] = "no-store"
    return await runtime.run(body)


def _event(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(payload, separators=(",", ":"), default=str)}


@router.post("/chat/stream", dependencies=[Depends(enforce_chat_limit)])
async def chat_stream(
    body: ChatRequest,
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> EventSourceResponse:
    stream_run_id = uuid4()

    async def events() -> Any:
        yield _event("run_started", {"run_id": str(stream_run_id)})
        yield _event("step_started", {"name": "agent_graph"})
        try:
            response = await runtime.run(body, run_id=stream_run_id)
        except AppError as exc:
            yield _event("error", {"code": exc.code, "message": exc.message})
            return
        except Exception:
            yield _event("error", {"code": "AI_FAILED", "message": "The assistant failed safely"})
            return
        for step in response.steps:
            yield _event("step_completed", step.model_dump(mode="json"))
        for citation in response.citations:
            yield _event("citation", citation.model_dump(mode="json"))
        yield _event("final", response.model_dump(mode="json"))

    return EventSourceResponse(events(), ping=15, headers={"Cache-Control": "no-store"})


@router.post("/chat/{run_id}/feedback", response_model=FeedbackResponse)
async def feedback(
    run_id: UUID,
    body: FeedbackRequest,
    response: Response,
    trace: Annotated[TraceManager, Depends(get_trace_manager)],
) -> FeedbackResponse:
    response.headers["Cache-Control"] = "no-store"
    if not trace.enabled:
        raise AppError(503, "FEEDBACK_UNAVAILABLE", "Feedback requires LangSmith tracing")
    attached = trace.feedback(
        run_id,
        score=body.score,
        reason=body.reason,
        correction=body.correction,
    )
    if not attached:
        raise AppError(404, "RUN_NOT_FOUND", "The trace is not available for feedback")
    return FeedbackResponse(accepted=True, trace_attached=True)

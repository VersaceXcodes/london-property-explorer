from __future__ import annotations

from typing import Any, Literal, TypedDict

from api.app.ai.contracts import SQLPlan
from api.app.models import Citation, MapAction


class Evidence(TypedDict):
    id: str
    content: str
    title: str
    section: str | None
    publisher: str
    url: str
    licence: str | None
    score: float | None


class StepRecord(TypedDict):
    name: str
    status: Literal["completed", "degraded", "failed"]
    detail: str
    duration_ms: int


class AgentState(TypedDict, total=False):
    run_id: str
    messages: list[dict[str, str]]
    question: str
    route: Literal["sql", "rag", "hybrid", "map_action", "unsupported"]
    route_reason: str
    sql_plan: SQLPlan
    sql_facts: list[dict[str, Any]]
    evidence: list[Evidence]
    citations: list[Citation]
    draft_cited_ids: list[str]
    map_action: MapAction | None
    reply: str
    steps: list[StepRecord]
    degraded: bool
    validation_result: str
    verification_attempts: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    prompt_hash: str
    started_at: float

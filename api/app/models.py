from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PropertyType = Literal["D", "S", "T", "F", "O"]
Tenure = Literal["F", "L"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class QueryFilterModel(StrictModel):
    min_price: int | None = Field(default=None, ge=0, le=50_000_000)
    max_price: int | None = Field(default=None, ge=0, le=50_000_000)
    types: list[PropertyType] | None = None
    tenures: list[Tenure] | None = None
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def validate_ranges(self) -> QueryFilterModel:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must be <= max_price")
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("from must be <= to")
        if self.types is not None and len(set(self.types)) != len(self.types):
            raise ValueError("types must be unique")
        if self.tenures is not None and len(set(self.tenures)) != len(self.tenures):
            raise ValueError("tenures must be unique")
        return self


class ClusterCell(StrictModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    count: int = Field(gt=0)
    median_price: int = Field(ge=10_000, le=50_000_000)


class ClustersResponse(StrictModel):
    mode: Literal["clusters"] = "clusters"
    cells: list[ClusterCell]


class TransactionPoint(StrictModel):
    id: UUID
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    price: int = Field(ge=10_000, le=50_000_000)
    type: PropertyType
    date: date
    postcode: str = Field(pattern=r"^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$")


class PointsResponse(StrictModel):
    mode: Literal["points"] = "points"
    truncated: bool
    points: list[TransactionPoint] = Field(max_length=25_000)


class DistrictStats(StrictModel):
    district: str = Field(pattern=r"^[A-Z]{1,2}[0-9][0-9A-Z]?$")
    sales: int = Field(gt=0)
    median_price: int = Field(ge=10_000, le=50_000_000)


class HistoryEntry(StrictModel):
    id: UUID
    price: int = Field(ge=10_000, le=50_000_000)
    date: date
    type: PropertyType
    tenure: Tenure
    is_new: bool
    paon: str | None
    saon: str | None
    street: str | None
    town: str | None


class PostcodeHistory(StrictModel):
    postcode: str = Field(pattern=r"^[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}$")
    count: int = Field(ge=1, le=200)
    truncated: bool
    entries: list[HistoryEntry] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_count(self) -> PostcodeHistory:
        if self.count != len(self.entries):
            raise ValueError("count must equal entries length")
        if self.truncated and self.count != 200:
            raise ValueError("truncated history must return 200 entries")
        return self


class MetaResponse(StrictModel):
    total: int = Field(gt=0)
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"


class CapabilityResponse(StrictModel):
    chat: bool
    rag: bool
    tracing: bool
    streaming: bool
    feedback: bool
    graph_version: str
    corpus_version: str | None


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)


class ChatRequest(StrictModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_conversation(self) -> ChatRequest:
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("conversation must start and end with a user message")
        if any(
            left.role == right.role
            for left, right in zip(self.messages, self.messages[1:], strict=False)
        ):
            raise ValueError("message roles must alternate")
        if any(len(message.content) > 500 for message in self.messages if message.role == "user"):
            raise ValueError("individual user messages cannot exceed 500 characters")
        total_text = sum(len(message.content) for message in self.messages)
        if total_text > 6_000:
            raise ValueError("combined conversation exceeds 6000 characters")
        return self


class Citation(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    section: str | None = Field(default=None, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https?://")
    licence: str | None = Field(default=None, max_length=200)


class ChatStep(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    status: Literal["completed", "degraded", "failed"]
    detail: str = Field(min_length=1, max_length=300)
    duration_ms: int = Field(ge=0)


class MapAction(StrictModel):
    kind: Literal["set_filters", "highlight_district"]
    payload: dict[str, object]
    label: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_payload(self) -> MapAction:
        if self.kind == "highlight_district":
            if set(self.payload) != {"district"}:
                raise ValueError("highlight_district requires only a district payload")
            district = self.payload["district"]
            if not isinstance(district, str) or not re.fullmatch(
                r"[A-Z]{1,2}[0-9][0-9A-Z]?", district
            ):
                raise ValueError("district must be a canonical postcode district")
            return self
        if not self.payload:
            raise ValueError("set_filters requires at least one filter")
        QueryFilterModel.model_validate(self.payload)
        return self


class AgentMetrics(StrictModel):
    route: Literal["sql", "rag", "hybrid", "map_action", "unsupported"]
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    graph_version: str
    prompt_hash: str
    model: str
    corpus_version: str | None


class ChatResponse(StrictModel):
    run_id: UUID
    reply: str = Field(min_length=1, max_length=8_000)
    citations: list[Citation] = Field(max_length=10)
    steps: list[ChatStep] = Field(max_length=20)
    map_action: MapAction | None = None
    degraded: bool = False
    metrics: AgentMetrics


class FeedbackRequest(StrictModel):
    score: Literal[-1, 1]
    reason: str | None = Field(default=None, max_length=500)
    correction: str | None = Field(default=None, max_length=2_000)


class FeedbackResponse(StrictModel):
    accepted: bool
    trace_attached: bool


def parse_types(value: str | None) -> list[PropertyType] | None:
    if value is None or value == "":
        return None
    parts = value.split(",")
    allowed = {"D", "S", "T", "F", "O"}
    if (
        len(parts) > 5
        or any(part not in allowed for part in parts)
        or len(parts) != len(set(parts))
    ):
        raise ValueError("types must be unique comma-separated values from D,S,T,F,O")
    return parts  # type: ignore[return-value]


def parse_tenures(value: str | None) -> list[Tenure] | None:
    if value is None or value == "":
        return None
    parts = value.split(",")
    allowed = {"F", "L"}
    if (
        len(parts) > 2
        or any(part not in allowed for part in parts)
        or len(parts) != len(set(parts))
    ):
        raise ValueError("tenures must be unique comma-separated values from F,L")
    return parts  # type: ignore[return-value]


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        parts = tuple(float(part) for part in value.split(","))
    except ValueError as exc:
        raise ValueError("bbox must contain four finite numbers") from exc
    if len(parts) != 4:
        raise ValueError("bbox must contain four values")
    min_lng, min_lat, max_lng, max_lat = parts
    if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox bounds are invalid or inverted")
    return min_lng, min_lat, max_lng, max_lat


Price = Annotated[int, Field(ge=10_000, le=50_000_000)]

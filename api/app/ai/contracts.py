from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AggregatePlan(AIModel):
    kind: Literal["aggregate"] = "aggregate"
    districts: list[str] | None = Field(default=None, max_length=20)
    min_price: int | None = Field(default=None, ge=0, le=50_000_000)
    max_price: int | None = Field(default=None, ge=0, le=50_000_000)
    types: list[Literal["D", "S", "T", "F", "O"]] | None = Field(default=None, max_length=5)
    tenures: list[Literal["F", "L"]] | None = Field(default=None, max_length=2)
    from_date: date | None = None
    to_date: date | None = None
    group_by: Literal["year", "month", "district", "property_type"] | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> AggregatePlan:
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
            raise ValueError("from_date must be <= to_date")
        if self.districts is not None:
            if len(set(self.districts)) != len(self.districts):
                raise ValueError("districts must be unique")
            if any(
                re.fullmatch(r"[A-Z]{1,2}[0-9][0-9A-Z]?", district) is None
                for district in self.districts
            ):
                raise ValueError("districts must be canonical postcode districts")
        if self.types is not None and len(set(self.types)) != len(self.types):
            raise ValueError("types must be unique")
        if self.tenures is not None and len(set(self.tenures)) != len(self.tenures):
            raise ValueError("tenures must be unique")
        return self


class TopDistrictsPlan(AIModel):
    kind: Literal["top_districts"] = "top_districts"
    metric: Literal["sales", "median_price"]
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=5, ge=1, le=20)


class NoSQLPlan(AIModel):
    kind: Literal["none"] = "none"


class SQLPlan(AIModel):
    plan: AggregatePlan | TopDistrictsPlan | NoSQLPlan = Field(discriminator="kind")


class RouteDecision(AIModel):
    route: Literal["sql", "rag", "hybrid", "map_action", "unsupported"]
    reason: str = Field(min_length=1, max_length=200)


class AnswerDraft(AIModel):
    reply: str = Field(min_length=1, max_length=8_000)
    cited_ids: list[str] = Field(default_factory=list, max_length=10)


class ModelUsage(AIModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelResult[T: BaseModel](AIModel):
    value: T
    usage: ModelUsage = Field(default_factory=ModelUsage)

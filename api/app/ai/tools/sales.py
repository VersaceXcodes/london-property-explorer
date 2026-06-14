from __future__ import annotations

from typing import Any

from api.app.ai.contracts import AggregatePlan, SQLPlan, TopDistrictsPlan
from api.app.db.repository import Repository


async def execute_sales_plan(repository: Repository, request: SQLPlan) -> list[dict[str, Any]]:
    plan = request.plan
    if isinstance(plan, AggregatePlan):
        return await repository.aggregate_sales(plan)
    if isinstance(plan, TopDistrictsPlan):
        return await repository.top_districts(plan.metric, plan.order, plan.limit)
    return []

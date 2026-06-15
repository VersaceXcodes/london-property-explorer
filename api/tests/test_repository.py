from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from api.app.ai.contracts import AggregatePlan
from api.app.db import queries
from api.app.db.repository import PostgresRepository


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        del args
        self.calls.append(query)
        if query == queries.META:
            return [
                {
                    "total": 466_368,
                    "from": date(2021, 1, 1),
                    "to": date(2026, 4, 30),
                }
            ]
        raise AssertionError(f"unexpected query: {query}")


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


@pytest.mark.asyncio
async def test_unfiltered_postgres_aggregate_uses_dataset_meta() -> None:
    connection = FakeConnection()
    repository = PostgresRepository(FakePool(connection))  # type: ignore[arg-type]

    rows = await repository.aggregate_sales(AggregatePlan())

    assert rows == [
        {
            "group": None,
            "sales": 466_368,
            "median_price": None,
            "from": date(2021, 1, 1),
            "to": date(2026, 4, 30),
        }
    ]
    assert connection.calls == [queries.META]

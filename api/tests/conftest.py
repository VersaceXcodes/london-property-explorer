from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app.core.config import Settings
from api.app.main import create_app


class FakeRepository:
    async def health(self) -> None:
        return None

    async def clusters(self, *_: object, **__: object) -> list[dict[str, Any]]:
        return [{"lng": -0.12, "lat": 51.5, "count": 10, "median_price": 500_000}]

    async def points(self, *_: object, **__: object) -> list[dict[str, Any]]:
        return [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "lng": -0.16,
                "lat": 51.47,
                "price": 485_000,
                "type": "F",
                "date": date(2024, 3, 1),
                "postcode": "SW11 4NB",
            }
        ]

    async def postcode_history(self, _: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "price": 485_000,
                "date": date(2024, 3, 1),
                "type": "F",
                "tenure": "L",
                "is_new": False,
                "paon": "12",
                "saon": "FLAT 2",
                "street": "EXAMPLE ROAD",
                "town": "LONDON",
            }
        ]

    async def district_stats(self) -> list[dict[str, Any]]:
        return [{"district": "SW11", "sales": 100, "median_price": 600_000}]

    async def districts(self) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": []}

    async def meta(self) -> dict[str, Any]:
        return {"total": 466_368, "from": date(2021, 1, 1), "to": date(2026, 4, 30)}

    async def aggregate_sales(self, *_: object, **__: object) -> list[dict[str, Any]]:
        return [{"group": None, "sales": 100, "median_price": 600_000}]

    async def top_districts(self, *_: object, **__: object) -> list[dict[str, Any]]:
        return await self.district_stats()


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(repository: FakeRepository) -> Iterator[TestClient]:
    app = create_app(
        settings=Settings(
            database_url=None,
            ai_provider="anthropic",
            anthropic_api_key=None,
            openrouter_api_key=None,
            pinecone_api_key=None,
            langsmith_api_key=None,
            langsmith_tracing=False,
        ),
        repository=repository,
    )
    with TestClient(app) as test_client:
        yield test_client

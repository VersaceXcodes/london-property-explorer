from __future__ import annotations

import csv
from pathlib import Path

import pytest

from api.app.ai.contracts import AggregatePlan
from api.app.db.sqlite_repository import SqliteRepository
from api.app.models import QueryFilterModel
from scripts.build_local_sqlite import create_sqlite_from_csv


def write_final_csv(path: Path) -> None:
    rows = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "price": "400000",
            "date": "2024-01-01",
            "postcode": "SW11 4NB",
            "district": "SW11",
            "property_type": "F",
            "is_new": "false",
            "tenure": "L",
            "paon": "1",
            "saon": "",
            "street": "ALPHA ROAD",
            "town": "LONDON",
            "longitude": "-0.160000",
            "latitude": "51.470000",
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "price": "600000",
            "date": "2024-02-01",
            "postcode": "SW11 4NB",
            "district": "SW11",
            "property_type": "T",
            "is_new": "true",
            "tenure": "F",
            "paon": "2",
            "saon": "",
            "street": "ALPHA ROAD",
            "town": "LONDON",
            "longitude": "-0.161000",
            "latitude": "51.471000",
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "price": "900000",
            "date": "2024-03-01",
            "postcode": "E1 6AN",
            "district": "E1",
            "property_type": "F",
            "is_new": "false",
            "tenure": "L",
            "paon": "3",
            "saon": "FLAT 1",
            "street": "BETA STREET",
            "town": "LONDON",
            "longitude": "-0.070000",
            "latitude": "51.520000",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def sqlite_repository(tmp_path: Path) -> SqliteRepository:
    csv_path = tmp_path / "transactions.csv"
    db_path = tmp_path / "lpe.sqlite3"
    write_final_csv(csv_path)
    create_sqlite_from_csv(csv_path, db_path, manifest={"test": True})
    return SqliteRepository(db_path)


async def test_sqlite_repository_serves_core_api_shapes(
    sqlite_repository: SqliteRepository,
) -> None:
    await sqlite_repository.health()
    filters = QueryFilterModel()
    clusters = await sqlite_repository.clusters((-0.3, 51.3, 0.1, 51.7), 10, 32, 10_000, filters)
    assert sum(row["count"] for row in clusters) == 3

    points = await sqlite_repository.points((-0.2, 51.4, -0.1, 51.5), filters, 2)
    assert [row["postcode"] for row in points] == ["SW11 4NB", "SW11 4NB"]

    leasehold_points = await sqlite_repository.points(
        (-0.2, 51.4, 0.0, 51.6), QueryFilterModel(tenures=["L"]), 10
    )
    assert sorted(row["id"] for row in leasehold_points) == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000003",
    ]

    history = await sqlite_repository.postcode_history("SW11 4NB")
    assert [row["date"] for row in history] == ["2024-02-01", "2024-01-01"]

    meta = await sqlite_repository.meta()
    assert meta == {"total": 3, "from": "2024-01-01", "to": "2024-03-01"}
    districts = await sqlite_repository.districts()
    assert districts["features"][0]["geometry"]["type"] == "MultiPolygon"


async def test_sqlite_repository_supports_ai_sql_tools(
    sqlite_repository: SqliteRepository,
) -> None:
    aggregate = await sqlite_repository.aggregate_sales(
        AggregatePlan(districts=["SW11"], group_by="property_type", tenures=["F"])
    )
    assert aggregate == [
        {"group": "T", "sales": 1, "median_price": 600000},
    ]

    top = await sqlite_repository.top_districts("median_price", "desc", 1)
    assert top == [{"district": "E1", "sales": 1, "median_price": 900000}]

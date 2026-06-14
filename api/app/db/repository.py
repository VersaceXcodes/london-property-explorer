from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol, cast

import asyncpg

from api.app.core.errors import AppError

from . import queries

Row = dict[str, Any]


class Repository(Protocol):
    async def health(self) -> None: ...
    async def clusters(
        self,
        bbox: tuple[float, float, float, float],
        zoom: int,
        cell_px: int,
        cell: float,
        filters: QueryFilters,
    ) -> list[Row]: ...
    async def points(
        self, bbox: tuple[float, float, float, float], filters: QueryFilters, limit: int
    ) -> list[Row]: ...
    async def postcode_history(self, postcode: str) -> list[Row]: ...
    async def district_stats(self) -> list[Row]: ...
    async def districts(self) -> dict[str, Any]: ...
    async def meta(self) -> Row: ...
    async def aggregate_sales(self, filters: AggregateFilters) -> list[Row]: ...
    async def top_districts(self, metric: str, order: str, limit: int) -> list[Row]: ...


class QueryFilters(Protocol):
    @property
    def min_price(self) -> int | None: ...

    @property
    def max_price(self) -> int | None: ...

    @property
    def types(self) -> Sequence[str] | None: ...

    @property
    def tenures(self) -> Sequence[str] | None: ...

    @property
    def from_date(self) -> date | None: ...

    @property
    def to_date(self) -> date | None: ...


class AggregateFilters(QueryFilters, Protocol):
    @property
    def districts(self) -> Sequence[str] | None: ...

    @property
    def group_by(self) -> str | None: ...


class PostgresRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def _fetch(self, query: str, *args: object) -> list[Row]:
        try:
            async with self.pool.acquire() as connection:
                records = await connection.fetch(query, *args)
        except (TimeoutError, asyncpg.PostgresError) as exc:
            raise AppError(503, "DB_TIMEOUT", "Database query failed or timed out") from exc
        return [dict(record) for record in records]

    async def _fetchrow(self, query: str, *args: object) -> Row:
        rows = await self._fetch(query, *args)
        if not rows:
            raise AppError(503, "QUERY_FAILED", "Database returned no result")
        return rows[0]

    async def health(self) -> None:
        await self._fetchrow("SELECT 1 AS ok")

    async def clusters(
        self,
        bbox: tuple[float, float, float, float],
        zoom: int,
        cell_px: int,
        cell: float,
        filters: QueryFilters,
    ) -> list[Row]:
        if (
            6 <= zoom <= 11
            and filters.min_price is None
            and filters.max_price is None
            and filters.types is None
            and filters.tenures is None
            and filters.from_date is None
            and filters.to_date is None
        ):
            return await self._fetch(queries.PRECOMPUTED_CLUSTERS, zoom, cell_px, *bbox)
        return await self._fetch(
            queries.CLUSTERS,
            *bbox,
            cell,
            filters.min_price,
            filters.max_price,
            filters.types,
            filters.tenures,
            filters.from_date,
            filters.to_date,
        )

    async def points(
        self, bbox: tuple[float, float, float, float], filters: QueryFilters, limit: int
    ) -> list[Row]:
        return await self._fetch(
            queries.POINTS,
            *bbox,
            filters.min_price,
            filters.max_price,
            filters.types,
            filters.tenures,
            filters.from_date,
            filters.to_date,
            limit,
        )

    async def postcode_history(self, postcode: str) -> list[Row]:
        return await self._fetch(queries.POSTCODE_HISTORY, postcode)

    async def district_stats(self) -> list[Row]:
        return await self._fetch(queries.DISTRICT_STATS)

    async def districts(self) -> dict[str, Any]:
        row = await self._fetchrow(queries.DISTRICTS)
        value = row["feature_collection"]
        parsed = json.loads(value) if isinstance(value, str) else value
        return cast(dict[str, Any], parsed)

    async def meta(self) -> Row:
        return await self._fetchrow(queries.META)

    async def aggregate_sales(self, filters: AggregateFilters) -> list[Row]:
        expressions = {
            "year": "to_char(date_trunc('year', date), 'YYYY')",
            "month": "to_char(date_trunc('month', date), 'YYYY-MM')",
            "district": "district",
            "property_type": "property_type",
        }
        expression = expressions.get(filters.group_by or "")
        group_select = f'{expression} AS "group",' if expression else 'NULL::text AS "group",'
        group_clause = f"GROUP BY {expression} ORDER BY {expression}" if expression else ""
        query = f"""
        SELECT {group_select}
               count(*) AS sales,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::integer AS median_price
        FROM transactions
        WHERE ($1::text[] IS NULL OR district = ANY($1))
          AND ($2::integer IS NULL OR price >= $2)
          AND ($3::integer IS NULL OR price <= $3)
          AND ($4::text[] IS NULL OR property_type = ANY($4))
          AND ($5::text[] IS NULL OR tenure = ANY($5))
          AND ($6::date IS NULL OR date >= $6)
          AND ($7::date IS NULL OR date <= $7)
        {group_clause}
        LIMIT 60
        """
        return await self._fetch(
            query,
            filters.districts,
            filters.min_price,
            filters.max_price,
            filters.types,
            filters.tenures,
            filters.from_date,
            filters.to_date,
        )

    async def top_districts(self, metric: str, order: str, limit: int) -> list[Row]:
        return await self._fetch(queries.TOP_DISTRICTS, metric, order, limit)


class UnavailableRepository:
    async def _unavailable(self) -> None:
        raise AppError(503, "QUERY_FAILED", "Database is not configured")

    async def health(self) -> None:
        await self._unavailable()

    async def clusters(self, *_: object, **__: object) -> list[Row]:
        await self._unavailable()
        return []

    async def points(self, *_: object, **__: object) -> list[Row]:
        await self._unavailable()
        return []

    async def postcode_history(self, *_: object, **__: object) -> list[Row]:
        await self._unavailable()
        return []

    async def district_stats(self) -> list[Row]:
        await self._unavailable()
        return []

    async def districts(self) -> dict[str, Any]:
        await self._unavailable()
        return {}

    async def meta(self) -> Row:
        await self._unavailable()
        return {}

    async def aggregate_sales(self, *_: object, **__: object) -> list[Row]:
        await self._unavailable()
        return []

    async def top_districts(self, *_: object, **__: object) -> list[Row]:
        await self._unavailable()
        return []

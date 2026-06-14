from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from api.app.core.errors import AppError

from .repository import AggregateFilters, QueryFilters, Row

WEB_MERCATOR_ORIGIN = 20_037_508.342789244


class SqliteRepository:
    """Local read-only repository for full real-data development without PostGIS."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _rows(records: Sequence[sqlite3.Row]) -> list[Row]:
        return [dict(record) for record in records]

    async def _fetch(self, query: str, args: Sequence[object] = ()) -> list[Row]:
        def run() -> list[Row]:
            try:
                with self._connect() as connection:
                    return self._rows(connection.execute(query, tuple(args)).fetchall())
            except sqlite3.Error as exc:
                raise AppError(503, "QUERY_FAILED", "Local SQLite query failed") from exc

        return await asyncio.to_thread(run)

    async def _fetchrow(self, query: str, args: Sequence[object] = ()) -> Row:
        rows = await self._fetch(query, args)
        if not rows:
            raise AppError(503, "QUERY_FAILED", "Local SQLite returned no result")
        return rows[0]

    @staticmethod
    def _date(value: object) -> object:
        return value.isoformat() if hasattr(value, "isoformat") else value

    @classmethod
    def _filter_sql(
        cls,
        filters: QueryFilters,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        districts: Sequence[str] | None = None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        args: list[object] = []
        if bbox is not None:
            clauses.append("lng >= ? AND lat >= ? AND lng <= ? AND lat <= ?")
            args.extend(bbox)
        if districts:
            clauses.append(f"district IN ({','.join('?' for _ in districts)})")
            args.extend(districts)
        if filters.min_price is not None:
            clauses.append("price >= ?")
            args.append(filters.min_price)
        if filters.max_price is not None:
            clauses.append("price <= ?")
            args.append(filters.max_price)
        if filters.types:
            clauses.append(f"property_type IN ({','.join('?' for _ in filters.types)})")
            args.extend(filters.types)
        if filters.tenures:
            clauses.append(f"tenure IN ({','.join('?' for _ in filters.tenures)})")
            args.extend(filters.tenures)
        if filters.from_date is not None:
            clauses.append("date >= ?")
            args.append(cls._date(filters.from_date))
        if filters.to_date is not None:
            clauses.append("date <= ?")
            args.append(cls._date(filters.to_date))
        return (" AND ".join(clauses) if clauses else "1=1"), args

    async def health(self) -> None:
        await self._fetchrow("SELECT 1 AS ok")

    async def clusters(
        self,
        bbox: tuple[float, float, float, float],
        _: int,
        __: int,
        cell: float,
        filters: QueryFilters,
    ) -> list[Row]:
        where, args = self._filter_sql(filters, bbox=bbox)
        query = f"""
        WITH filtered AS (
          SELECT lng, lat, price,
                 CAST((x + ?) / ? AS INTEGER) AS gx,
                 CAST((y + ?) / ? AS INTEGER) AS gy
          FROM transactions
          WHERE {where}
        ),
        summary AS (
          SELECT gx, gy, avg(lng) AS lng, avg(lat) AS lat, count(*) AS count
          FROM filtered
          GROUP BY gx, gy
        ),
        ranked AS (
          SELECT gx, gy, price,
                 row_number() OVER (PARTITION BY gx, gy ORDER BY price) AS rn,
                 count(*) OVER (PARTITION BY gx, gy) AS cnt
          FROM filtered
        ),
        medians AS (
          SELECT gx, gy, CAST(avg(price) AS INTEGER) AS median_price
          FROM ranked
          WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
          GROUP BY gx, gy
        )
        SELECT summary.lng, summary.lat, summary.count, medians.median_price
        FROM summary
        JOIN medians USING (gx, gy)
        ORDER BY summary.count DESC, summary.lng, summary.lat
        """
        return await self._fetch(
            query,
            [WEB_MERCATOR_ORIGIN, cell, WEB_MERCATOR_ORIGIN, cell, *args],
        )

    async def points(
        self, bbox: tuple[float, float, float, float], filters: QueryFilters, limit: int
    ) -> list[Row]:
        where, args = self._filter_sql(filters, bbox=bbox)
        center_lng = (bbox[0] + bbox[2]) / 2.0
        center_lat = (bbox[1] + bbox[3]) / 2.0
        query = f"""
        SELECT id, lng, lat, price, property_type AS type, date, postcode
        FROM transactions
        WHERE {where}
        ORDER BY ((lng - ?) * (lng - ?) + (lat - ?) * (lat - ?)) ASC, id ASC
        LIMIT ?
        """
        return await self._fetch(
            query, [*args, center_lng, center_lng, center_lat, center_lat, limit]
        )

    async def postcode_history(self, postcode: str) -> list[Row]:
        return await self._fetch(
            """
            SELECT id, price, date, property_type AS type, tenure, is_new,
                   paon, saon, street, town
            FROM transactions
            WHERE postcode = ?
            ORDER BY date DESC, id DESC
            LIMIT 201
            """,
            [postcode],
        )

    async def district_stats(self) -> list[Row]:
        return await self._fetch(
            "SELECT district, sales, median_price FROM district_stats ORDER BY district"
        )

    async def districts(self) -> dict[str, Any]:
        rows = await self._fetch(
            """
            SELECT district, min_lng, min_lat, max_lng, max_lat
            FROM district_bounds
            ORDER BY district
            """
        )
        features: list[dict[str, Any]] = []
        for row in rows:
            min_lng = float(row["min_lng"])
            min_lat = float(row["min_lat"])
            max_lng = float(row["max_lng"])
            max_lat = float(row["max_lat"])
            ring = [
                [min_lng, min_lat],
                [max_lng, min_lat],
                [max_lng, max_lat],
                [min_lng, max_lat],
                [min_lng, min_lat],
            ]
            features.append(
                {
                    "type": "Feature",
                    "properties": {"code": row["district"]},
                    "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    async def meta(self) -> Row:
        return await self._fetchrow(
            'SELECT total, from_date AS "from", to_date AS "to" FROM dataset_meta'
        )

    async def aggregate_sales(self, filters: AggregateFilters) -> list[Row]:
        group_expressions = {
            "year": "substr(date, 1, 4)",
            "month": "substr(date, 1, 7)",
            "district": "district",
            "property_type": "property_type",
        }
        group_expr = group_expressions.get(filters.group_by or "", "NULL")
        where, args = self._filter_sql(filters, districts=filters.districts)
        query = f"""
        WITH filtered AS (
          SELECT {group_expr} AS bucket, price
          FROM transactions
          WHERE {where}
        ),
        ranked AS (
          SELECT bucket, price,
                 row_number() OVER (PARTITION BY bucket ORDER BY price) AS rn,
                 count(*) OVER (PARTITION BY bucket) AS cnt
          FROM filtered
        )
        SELECT bucket AS "group", max(cnt) AS sales, CAST(avg(price) AS INTEGER) AS median_price
        FROM ranked
        WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
        GROUP BY bucket
        ORDER BY bucket
        LIMIT 60
        """
        return await self._fetch(query, args)

    async def top_districts(self, metric: str, order: str, limit: int) -> list[Row]:
        if metric not in {"sales", "median_price"} or order not in {"asc", "desc"}:
            raise AppError(400, "BAD_REQUEST", "Invalid district ranking")
        direction = "ASC" if order == "asc" else "DESC"
        return await self._fetch(
            f"""
            SELECT district, sales, median_price
            FROM district_stats
            ORDER BY {metric} {direction}, district ASC
            LIMIT ?
            """,
            [limit],
        )

    async def local_manifest(self) -> dict[str, Any] | None:
        rows = await self._fetch("SELECT value FROM local_metadata WHERE key = 'manifest'")
        if not rows:
            return None
        return cast(dict[str, Any], json.loads(str(rows[0]["value"])))

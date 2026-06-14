from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
WEB_MERCATOR_WORLD_METRES = 40_075_016.686
PRECOMPUTED_CLUSTER_ZOOMS = range(6, 12)
MANAGED_RELATION_BYTES = """
SELECT coalesce(sum(pg_total_relation_size(relation)), 0)
FROM unnest(ARRAY[
  to_regclass('public.transactions'),
  to_regclass('public.districts'),
  to_regclass('public.dataset_meta'),
  to_regclass('public.cluster_cells'),
  to_regclass('public.district_stats')
]) AS relation
WHERE relation IS NOT NULL
"""
PRECOMPUTE_CLUSTERS = """
WITH points AS (
  SELECT floor(ST_X(geom_3857) / $3::double precision)::integer AS cell_x,
         floor(ST_Y(geom_3857) / $3::double precision)::integer AS cell_y,
         geom_3857,
         price
  FROM transactions
),
cells AS (
  SELECT cell_x,
         cell_y,
         avg(ST_X(geom_3857)) AS center_x,
         avg(ST_Y(geom_3857)) AS center_y,
         count(*)::integer AS sale_count,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::integer AS median_price
  FROM points
  GROUP BY cell_x, cell_y
),
projected AS (
  SELECT cell_x,
         cell_y,
         sale_count,
         median_price,
         ST_Transform(ST_SetSRID(ST_MakePoint(center_x, center_y), 3857), 4326) AS geom,
         ST_Transform(
           ST_MakeEnvelope(
             cell_x * $3::double precision,
             cell_y * $3::double precision,
             (cell_x + 1) * $3::double precision,
             (cell_y + 1) * $3::double precision,
             3857
           ),
           4326
         ) AS bbox
  FROM cells
)
INSERT INTO cluster_cells (
  zoom, cell_px, cell_x, cell_y, lng, lat, sale_count, median_price, geom, bbox
)
SELECT $1::integer,
       $2::integer,
       cell_x,
       cell_y,
       ST_X(geom),
       ST_Y(geom),
       sale_count,
       median_price,
       geom,
       bbox
FROM projected
"""


def transaction_records(path: Path) -> Iterator[tuple[Any, ...]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield (
                UUID(row["id"]),
                int(row["price"]),
                date.fromisoformat(row["date"]),
                row["postcode"],
                row["district"],
                row["property_type"],
                row["is_new"] == "true",
                row["tenure"],
                row["paon"] or None,
                row["saon"] or None,
                row["street"] or None,
                row["town"] or None,
                float(row["longitude"]),
                float(row["latitude"]),
            )


def cell_size_metres(zoom: int, cell_px: int) -> float:
    return float(WEB_MERCATOR_WORLD_METRES / (2**zoom) / 256 * cell_px)


async def load(
    database_url: str, output_dir: Path, app_reader_password: str, cell_px: int
) -> dict[str, int]:
    transactions_path = output_dir / "transactions.csv"
    districts_path = output_dir / "districts.geojson"
    manifest_path = output_dir / "source-manifest.json"
    for path in (transactions_path, districts_path, manifest_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_rows = int(manifest["counts"]["final_rows"])
    districts = json.loads(districts_path.read_text(encoding="utf-8"))
    connection = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        await connection.execute("SET statement_timeout = 0")
        initial_database_bytes = int(
            await connection.fetchval("SELECT pg_database_size(current_database())")
        )
        previous_relation_bytes = int(await connection.fetchval(MANAGED_RELATION_BYTES))
        async with connection.transaction():
            await connection.execute((ROOT / "pipeline/schema.sql").read_text(encoding="utf-8"))
            password_statement = await connection.fetchval(
                "SELECT format('ALTER ROLE app_reader PASSWORD %L', $1::text)",
                app_reader_password,
            )
            await connection.execute(str(password_statement))
            await connection.execute(
                """
                CREATE TEMP TABLE transaction_load (
                  id uuid, price integer, date date, postcode text, district text,
                  property_type char(1), is_new boolean, tenure char(1), paon text,
                  saon text, street text, town text, longitude double precision,
                  latitude double precision
                ) ON COMMIT DROP
                """
            )
            await connection.copy_records_to_table(
                "transaction_load",
                records=transaction_records(transactions_path),
                columns=[
                    "id",
                    "price",
                    "date",
                    "postcode",
                    "district",
                    "property_type",
                    "is_new",
                    "tenure",
                    "paon",
                    "saon",
                    "street",
                    "town",
                    "longitude",
                    "latitude",
                ],
            )
            await connection.execute(
                """
                INSERT INTO transactions (
                  id, price, date, postcode, district, property_type, is_new, tenure,
                  paon, saon, street, town, geom
                )
                SELECT id, price, date, postcode, district, property_type, is_new, tenure,
                       paon, saon, street, town,
                       ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
                FROM transaction_load
                """
            )
            await connection.execute(
                """
                INSERT INTO districts (code, geom)
                SELECT feature->'properties'->>'code',
                       ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(feature->>'geometry'), 4326))
                FROM json_array_elements(($1::json)->'features') AS feature
                """,
                json.dumps(districts),
            )
            for zoom in PRECOMPUTED_CLUSTER_ZOOMS:
                await connection.execute(
                    PRECOMPUTE_CLUSTERS,
                    zoom,
                    cell_px,
                    cell_size_metres(zoom, cell_px),
                )
            await connection.execute("REFRESH MATERIALIZED VIEW district_stats")
            actual_rows = int(await connection.fetchval("SELECT count(*) FROM transactions"))
            if actual_rows != expected_rows:
                raise RuntimeError(f"database row count {actual_rows} != manifest {expected_rows}")
            await connection.execute(
                """
                INSERT INTO dataset_meta (id, total, from_date, to_date, source_manifest)
                VALUES (true, $1, $2::date, $3::date, $4::jsonb)
                """,
                actual_rows,
                date.fromisoformat(manifest["counts"]["final_min_date"]),
                date.fromisoformat(manifest["counts"]["final_max_date"]),
                json.dumps(manifest),
            )
            await connection.execute(
                "ANALYZE transactions; ANALYZE districts; ANALYZE dataset_meta; "
                "ANALYZE cluster_cells"
            )
            relation_bytes = int(await connection.fetchval(MANAGED_RELATION_BYTES))
            predicted_database_bytes = (
                initial_database_bytes - previous_relation_bytes + relation_bytes
            )
            if predicted_database_bytes >= 450 * 1024 * 1024:
                raise RuntimeError(
                    "predicted database size "
                    f"{predicted_database_bytes} exceeds the 450 MB deployment gate"
                )
        database_bytes = int(
            await connection.fetchval("SELECT pg_database_size(current_database())")
        )
        return {
            "transactions": actual_rows,
            "cluster_cells": int(await connection.fetchval("SELECT count(*) FROM cluster_cells")),
            "dataset_meta": int(await connection.fetchval("SELECT count(*) FROM dataset_meta")),
            "relation_bytes": relation_bytes,
            "database_bytes": database_bytes,
        }
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load pipeline outputs into PostGIS")
    parser.add_argument("output_dir", nargs="?", type=Path, default=ROOT / "pipeline/output")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app_reader_password = os.environ.get("APP_READER_PASSWORD")
    if not app_reader_password:
        raise RuntimeError("APP_READER_PASSWORD is required")
    cell_px = int(os.environ.get("CELL_PX", "32"))
    if not 24 <= cell_px <= 64:
        raise RuntimeError("CELL_PX must be between 24 and 64")
    result = asyncio.run(load(database_url, args.output_dir, app_reader_password, cell_px))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

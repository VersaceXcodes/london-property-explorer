from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pipeline.lpe_pipeline.build import (
    FINAL_FIELDS,
    KNOWN_SNAPSHOT_COUNTS,
    PipelineError,
    load_onspd_matches,
    sha256_file,
    spool_candidates,
    validate_gates,
    write_final,
)
from pipeline.lpe_pipeline.models import BuildCounters, SourceFingerprint

WEB_MERCATOR_RADIUS = 6_378_137.0
DEFAULT_PPD = Path.home() / "Downloads" / "pp-complete.csv"
DEFAULT_ONSPD = Path.home() / "Downloads" / "ONSPD_Online_Latest_Centroids_-966716609290186519.csv"
DEFAULT_OUTPUT = Path("data/local/lpe-local.sqlite3")


def mercator_x(longitude: float) -> float:
    return WEB_MERCATOR_RADIUS * math.radians(longitude)


def mercator_y(latitude: float) -> float:
    limited = max(min(latitude, 85.05112878), -85.05112878)
    radians = math.radians(limited)
    return WEB_MERCATOR_RADIUS * math.log(math.tan(math.pi / 4.0 + radians / 2.0))


def null_if_empty(value: str) -> str | None:
    return value if value != "" else None


def batched(rows: Iterable[tuple[object, ...]], size: int) -> Iterable[list[tuple[object, ...]]]:
    batch: list[tuple[object, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def iter_sqlite_rows(csv_path: Path) -> Iterable[tuple[object, ...]]:
    with csv_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        missing = set(FINAL_FIELDS).difference(reader.fieldnames or [])
        if missing:
            raise PipelineError(f"final CSV missing required headers: {sorted(missing)}")
        for row in reader:
            longitude = float(row["longitude"])
            latitude = float(row["latitude"])
            yield (
                row["id"],
                int(row["price"]),
                row["date"],
                row["postcode"],
                row["district"],
                row["property_type"],
                1 if row["is_new"] == "true" else 0,
                row["tenure"],
                null_if_empty(row["paon"]),
                null_if_empty(row["saon"]),
                null_if_empty(row["street"]),
                null_if_empty(row["town"]),
                longitude,
                latitude,
                mercator_x(longitude),
                mercator_y(latitude),
            )


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS district_stats;
        DROP TABLE IF EXISTS district_bounds;
        DROP TABLE IF EXISTS dataset_meta;
        DROP TABLE IF EXISTS local_metadata;

        CREATE TABLE transactions (
          id TEXT PRIMARY KEY,
          price INTEGER NOT NULL CHECK (price BETWEEN 10000 AND 50000000),
          date TEXT NOT NULL,
          postcode TEXT NOT NULL,
          district TEXT NOT NULL,
          property_type TEXT NOT NULL CHECK (property_type IN ('D','S','T','F','O')),
          is_new INTEGER NOT NULL CHECK (is_new IN (0,1)),
          tenure TEXT NOT NULL CHECK (tenure IN ('F','L')),
          paon TEXT,
          saon TEXT,
          street TEXT,
          town TEXT,
          lng REAL NOT NULL,
          lat REAL NOT NULL,
          x REAL NOT NULL,
          y REAL NOT NULL
        );

        CREATE INDEX transactions_lng_lat_idx ON transactions (lng, lat);
        CREATE INDEX transactions_date_idx ON transactions (date);
        CREATE INDEX transactions_postcode_idx ON transactions (postcode);
        CREATE INDEX transactions_district_idx ON transactions (district);
        CREATE INDEX transactions_type_idx ON transactions (property_type);

        CREATE TABLE district_stats (
          district TEXT PRIMARY KEY,
          sales INTEGER NOT NULL,
          median_price INTEGER NOT NULL
        );

        CREATE TABLE district_bounds (
          district TEXT PRIMARY KEY,
          min_lng REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lng REAL NOT NULL,
          max_lat REAL NOT NULL
        );

        CREATE TABLE dataset_meta (
          total INTEGER NOT NULL,
          from_date TEXT NOT NULL,
          to_date TEXT NOT NULL
        );

        CREATE TABLE local_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def populate_derived_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        INSERT INTO district_stats (district, sales, median_price)
        WITH ranked AS (
          SELECT district, price,
                 row_number() OVER (PARTITION BY district ORDER BY price) AS rn,
                 count(*) OVER (PARTITION BY district) AS cnt
          FROM transactions
        )
        SELECT district, max(cnt) AS sales, CAST(avg(price) AS INTEGER) AS median_price
        FROM ranked
        WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
        GROUP BY district;

        INSERT INTO district_bounds (district, min_lng, min_lat, max_lng, max_lat)
        SELECT district,
               min(lng) - 0.003,
               min(lat) - 0.003,
               max(lng) + 0.003,
               max(lat) + 0.003
        FROM transactions
        GROUP BY district;

        INSERT INTO dataset_meta (total, from_date, to_date)
        SELECT count(*), min(date), max(date)
        FROM transactions;
        """
    )


def create_sqlite_from_csv(
    csv_path: Path, output_path: Path, manifest: dict[str, Any] | None = None
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    with sqlite3.connect(temporary_path) as connection:
        create_schema(connection)
        insert_sql = """
        INSERT INTO transactions (
          id, price, date, postcode, district, property_type, is_new, tenure,
          paon, saon, street, town, lng, lat, x, y
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for batch in batched(iter_sqlite_rows(csv_path), 10_000):
            connection.executemany(insert_sql, batch)
        populate_derived_tables(connection)
        if manifest is not None:
            connection.execute(
                "INSERT INTO local_metadata (key, value) VALUES ('manifest', ?)",
                (json.dumps(manifest, sort_keys=True),),
            )
        connection.execute("ANALYZE")
    os.replace(temporary_path, output_path)


def build_final_csv(ppd_path: Path, onspd_path: Path, work_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    counters = BuildCounters()
    ppd_digest = sha256_file(ppd_path)
    onspd_digest = sha256_file(onspd_path)
    spool_path = work_dir / "candidates.csv"
    final_path = work_dir / "transactions.csv"
    needed = spool_candidates(ppd_path, spool_path, counters)
    matches = load_onspd_matches(onspd_path, needed, counters)
    bounds = write_final(spool_path, final_path, matches, counters)
    validate_gates(counters, ppd_digest, onspd_digest)
    return {
        "schema_version": 1,
        "built_for": "local-sqlite-real-data",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "known_snapshot": (ppd_digest, onspd_digest) in KNOWN_SNAPSHOT_COUNTS,
        "sources": {
            "ppd": asdict(SourceFingerprint.from_path(ppd_path, ppd_digest)),
            "onspd": asdict(SourceFingerprint.from_path(onspd_path, onspd_digest)),
        },
        "counts": counters.to_dict(),
        "date_ranges": {
            "source": [counters.source_min_date, counters.source_max_date],
            "final": [counters.final_min_date, counters.final_max_date],
        },
        "coordinate_bounds": bounds,
        "transactions_csv": str(final_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local SQLite read model from the real downloaded PPD/ONSPD CSVs."
    )
    parser.add_argument("--ppd", type=Path, default=DEFAULT_PPD)
    parser.add_argument("--onspd", type=Path, default=DEFAULT_ONSPD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--from-transactions-csv",
        type=Path,
        help=(
            "Skip the source scan and build SQLite from an existing "
            "pipeline/output/transactions.csv."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing SQLite file.")
    args = parser.parse_args()

    if args.out.exists() and not args.force:
        raise SystemExit(f"{args.out} exists; pass --force to replace it")
    if args.from_transactions_csv is not None:
        create_sqlite_from_csv(args.from_transactions_csv, args.out)
        return

    if not args.ppd.exists():
        raise SystemExit(f"PPD file not found: {args.ppd}")
    if not args.onspd.exists():
        raise SystemExit(f"ONSPD file not found: {args.onspd}")

    with tempfile.TemporaryDirectory(prefix="lpe-local-sqlite-") as temp_dir:
        work_dir = Path(temp_dir)
        manifest = build_final_csv(args.ppd, args.onspd, work_dir)
        create_sqlite_from_csv(Path(manifest["transactions_csv"]), args.out, manifest)


if __name__ == "__main__":
    main()

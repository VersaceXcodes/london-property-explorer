from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO, Any

from .districts import merge_district_geojson
from .models import BuildCounters, OnspdRecord, SourceFingerprint
from .postcodes import canonical_postcode, postcode_district, postcode_join_key

PPD_COLUMNS = 16
MIN_DATE = date(2021, 1, 1)
MIN_PRICE = 10_000
MAX_PRICE = 50_000_000
LONDON_LADS = frozenset(f"E090000{i:02d}" for i in range(1, 34))
UK_LONGITUDE_BOUNDS = (-9.0, 3.0)
UK_LATITUDE_BOUNDS = (49.0, 61.0)
ALLOWED_PROPERTY_TYPES = frozenset("DSTFO")
ALLOWED_NEW_BUILD = frozenset("YN")
ALLOWED_TENURE = frozenset("FL")
KNOWN_SNAPSHOT_COUNTS = {
    (
        "3978dbd0da5439112c49839d0cb7c67b2bdef5b119207589d4796c776a57c0a9",
        "1ed3013cecac3aeab3cd7d5842ffcc819e754a71ae7bd256928d31ace2cf7c57",
    ): {
        "ppd_rows": 31_270_275,
        "selected_rows": 466_398,
        "selected_unique_postcodes": 105_151,
        "matched_unique_postcodes": 105_148,
        "unmatched_rows": 3,
        "outside_london_rows": 27,
        "final_rows": 466_368,
        "final_unique_postcodes": 105_130,
        "terminated_rows": 35,
        "source_min_date": "1995-01-01",
        "source_max_date": "2026-04-30",
        "final_min_date": "2021-01-01",
        "final_max_date": "2026-04-30",
        "property_types": {"D": 22_436, "S": 69_144, "T": 126_741, "F": 248_077},
        "new_build_codes": {"Y": 39_975, "N": 426_423},
        "tenure_codes": {"F": 213_281, "L": 253_117},
    }
}
CANDIDATE_FIELDS = [
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
    "join_key",
]
FINAL_FIELDS = CANDIDATE_FIELDS[:-1] + ["longitude", "latitude"]


class PipelineError(RuntimeError):
    """Raised when a source or data-quality gate fails."""


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def csv_field_size_limit() -> Iterator[None]:
    old_limit = csv.field_size_limit()
    csv.field_size_limit(10 * 1024 * 1024)
    try:
        yield
    finally:
        csv.field_size_limit(old_limit)


def parse_transfer_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise PipelineError(f"invalid PPD transfer date: {raw!r}") from exc


def _validate_domain(value: str, allowed: frozenset[str], field_name: str) -> None:
    if value not in allowed:
        raise PipelineError(f"unexpected {field_name} value: {value!r}")


def _candidate_from_ppd(row: list[str], counters: BuildCounters) -> dict[str, str] | None:
    if len(row) != PPD_COLUMNS:
        counters.malformed_ppd_rows += 1
        raise PipelineError(f"PPD row has {len(row)} columns, expected {PPD_COLUMNS}")

    try:
        transfer_date = parse_transfer_date(row[2])
    except PipelineError:
        counters.invalid_dates += 1
        raise
    counters.observe_date("source", transfer_date)
    try:
        price = int(row[1])
    except ValueError as exc:
        counters.invalid_prices += 1
        raise PipelineError(f"invalid PPD price: {row[1]!r}") from exc

    if not (
        transfer_date >= MIN_DATE
        and row[13] == "GREATER LONDON"
        and row[14] == "A"
        and row[15] == "A"
        and row[3].strip()
        and MIN_PRICE <= price <= MAX_PRICE
    ):
        return None

    _validate_domain(row[4], ALLOWED_PROPERTY_TYPES, "property_type")
    _validate_domain(row[5], ALLOWED_NEW_BUILD, "old_new")
    _validate_domain(row[6], ALLOWED_TENURE, "duration")
    counters.increment_domain("property_types", row[4])
    counters.increment_domain("new_build_codes", row[5])
    counters.increment_domain("tenure_codes", row[6])

    try:
        postcode = canonical_postcode(row[3])
    except ValueError as exc:
        counters.invalid_postcodes += 1
        raise PipelineError(str(exc)) from exc
    transaction_id = row[0].strip().strip("{}")
    if not transaction_id:
        raise PipelineError("empty transaction id")
    return {
        "id": transaction_id,
        "price": str(price),
        "date": transfer_date.isoformat(),
        "postcode": postcode,
        "district": postcode_district(postcode),
        "property_type": row[4],
        "is_new": "true" if row[5] == "Y" else "false",
        "tenure": row[6],
        "paon": row[7].strip(),
        "saon": row[8].strip(),
        "street": row[9].strip(),
        "town": row[11].strip(),
        "join_key": postcode_join_key(postcode),
    }


def spool_candidates(ppd_path: Path, spool_path: Path, counters: BuildCounters) -> set[str]:
    postcodes: set[str] = set()
    with (
        csv_field_size_limit(),
        ppd_path.open("r", encoding="utf-8-sig", newline="") as source,
        spool_path.open("w", encoding="utf-8", newline="") as target,
    ):
        writer = csv.DictWriter(target, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for row in csv.reader(source):
            counters.ppd_rows += 1
            candidate = _candidate_from_ppd(row, counters)
            if candidate is None:
                continue
            writer.writerow(candidate)
            counters.selected_rows += 1
            postcodes.add(candidate["join_key"])
    counters.selected_unique_postcodes = len(postcodes)
    return postcodes


def _parse_coordinate(raw: str, field_name: str, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise PipelineError(f"invalid ONSPD {field_name}: {raw!r}") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise PipelineError(f"out-of-range ONSPD {field_name}: {value}")
    return value


def load_onspd_matches(
    onspd_path: Path, needed: set[str], counters: BuildCounters
) -> dict[str, OnspdRecord]:
    matches: dict[str, OnspdRecord] = {}
    with (
        tempfile.TemporaryDirectory(prefix="lpe-onspd-keys-") as key_dir,
        sqlite3.connect(Path(key_dir) / "keys.sqlite3") as key_database,
        csv_field_size_limit(),
        onspd_path.open("r", encoding="utf-8-sig", newline="") as source,
    ):
        key_database.execute("PRAGMA journal_mode=OFF")
        key_database.execute("PRAGMA synchronous=OFF")
        key_database.execute("CREATE TABLE seen (key TEXT PRIMARY KEY) WITHOUT ROWID")
        reader = csv.DictReader(source)
        required = {"PCDS", "DOTERM", "LAD25CD", "LAT", "LONG"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise PipelineError(f"ONSPD missing required headers: {sorted(missing)}")
        key_batch: list[tuple[str]] = []

        def flush_keys() -> None:
            if not key_batch:
                return
            try:
                key_database.executemany("INSERT INTO seen (key) VALUES (?)", key_batch)
            except sqlite3.IntegrityError as exc:
                counters.duplicate_onspd_keys += 1
                raise PipelineError("duplicate canonical ONSPD key detected") from exc
            key_batch.clear()

        for row in reader:
            try:
                key = postcode_join_key(row["PCDS"])
            except ValueError:
                continue
            key_batch.append((key,))
            if len(key_batch) >= 10_000:
                flush_keys()
            if key not in needed:
                continue
            longitude = _parse_coordinate(row["LONG"], "LONG", -180.0, 180.0)
            latitude = _parse_coordinate(row["LAT"], "LAT", -90.0, 90.0)
            matches[key] = OnspdRecord(
                postcode=canonical_postcode(row["PCDS"]),
                lad_code=row["LAD25CD"].strip(),
                longitude=longitude,
                latitude=latitude,
                termination_date=row["DOTERM"].strip() or None,
            )
        flush_keys()
    counters.matched_unique_postcodes = len(matches)
    return matches


def write_final(
    spool_path: Path, output_path: Path, matches: dict[str, OnspdRecord], counters: BuildCounters
) -> dict[str, float]:
    final_postcodes: set[str] = set()
    bounds = {
        "min_longitude": math.inf,
        "min_latitude": math.inf,
        "max_longitude": -math.inf,
        "max_latitude": -math.inf,
    }
    with (
        spool_path.open("r", encoding="utf-8", newline="") as source,
        output_path.open("w", encoding="utf-8", newline="") as target,
    ):
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=FINAL_FIELDS)
        writer.writeheader()
        for row in reader:
            match = matches.get(row["join_key"])
            if match is None:
                counters.unmatched_rows += 1
                continue
            if match.lad_code not in LONDON_LADS:
                counters.outside_london_rows += 1
                continue
            if not (
                UK_LONGITUDE_BOUNDS[0] <= match.longitude <= UK_LONGITUDE_BOUNDS[1]
                and UK_LATITUDE_BOUNDS[0] <= match.latitude <= UK_LATITUDE_BOUNDS[1]
            ):
                counters.invalid_coordinate_rows += 1
                raise PipelineError(
                    f"retained postcode outside UK coordinate sanity bounds: {match.postcode}"
                )
            final_row = {field: row[field] for field in CANDIDATE_FIELDS[:-1]}
            final_row["longitude"] = f"{match.longitude:.6f}"
            final_row["latitude"] = f"{match.latitude:.6f}"
            writer.writerow(final_row)
            counters.final_rows += 1
            counters.observe_date("final", date.fromisoformat(row["date"]))
            counters.terminated_rows += int(match.termination_date is not None)
            final_postcodes.add(row["join_key"])
            bounds["min_longitude"] = min(bounds["min_longitude"], match.longitude)
            bounds["min_latitude"] = min(bounds["min_latitude"], match.latitude)
            bounds["max_longitude"] = max(bounds["max_longitude"], match.longitude)
            bounds["max_latitude"] = max(bounds["max_latitude"], match.latitude)
    counters.final_unique_postcodes = len(final_postcodes)
    return bounds


def validate_gates(counters: BuildCounters, ppd_sha256: str, onspd_sha256: str) -> None:
    if counters.malformed_ppd_rows:
        raise PipelineError("malformed PPD rows detected")
    if counters.duplicate_onspd_keys:
        raise PipelineError("duplicate ONSPD keys detected")
    if counters.invalid_coordinate_rows:
        raise PipelineError("invalid retained coordinates detected")
    if not 400_000 <= counters.final_rows <= 550_000:
        raise PipelineError(f"final row count outside drift gate: {counters.final_rows}")
    coverage = 1.0 - (counters.unmatched_rows / counters.selected_rows)
    if coverage < 0.999:
        raise PipelineError(f"ONSPD row-level join coverage below 99.9%: {coverage:.6%}")
    expected = KNOWN_SNAPSHOT_COUNTS.get((ppd_sha256, onspd_sha256))
    if expected:
        for field_name, value in expected.items():
            actual = getattr(counters, field_name)
            if actual != value:
                raise PipelineError(
                    f"known-snapshot mismatch for {field_name}: expected {value}, got {actual}"
                )


def _districts_in_csv(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as source:
        return {row["district"] for row in csv.DictReader(source)}


def _district_points_in_csv(path: Path) -> dict[str, list[tuple[float, float]]]:
    points: dict[str, list[tuple[float, float]]] = {}
    with path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            points.setdefault(row["district"], []).append(
                (float(row["longitude"]), float(row["latitude"]))
            )
    return points


def build_dataset(
    ppd_path: Path,
    onspd_path: Path,
    district_paths: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / "transactions.csv"
    manifest_path = output_dir / "source-manifest.json"
    validation_path = output_dir / "validation-report.json"
    districts_path = output_dir / "districts.geojson"
    counters = BuildCounters()
    ppd_digest = sha256_file(ppd_path)
    onspd_digest = sha256_file(onspd_path)

    with tempfile.TemporaryDirectory(prefix=".lpe-build-", dir=output_dir) as temp_dir:
        staging_dir = Path(temp_dir)
        spool_path = staging_dir / "candidates.csv"
        needed = spool_candidates(ppd_path, spool_path, counters)
        matches = load_onspd_matches(onspd_path, needed, counters)
        temporary_output = staging_dir / "transactions.csv"
        bounds = write_final(spool_path, temporary_output, matches, counters)
        validate_gates(counters, ppd_digest, onspd_digest)

        wanted_districts = _districts_in_csv(temporary_output)
        fallback_points = _district_points_in_csv(temporary_output)
        staged_districts = staging_dir / "districts.geojson"
        try:
            district_count = merge_district_geojson(
                district_paths, wanted_districts, staged_districts, fallback_points
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise PipelineError(f"invalid district boundary source: {exc}") from exc
        if district_count != len(wanted_districts):
            raise PipelineError(
                "district polygon coverage mismatch: "
                f"expected {len(wanted_districts)}, got {district_count}"
            )
        if staged_districts.stat().st_size >= 500 * 1024:
            raise PipelineError("district GeoJSON exceeds the 500 KB API payload gate")

        coverage = 1.0 - (counters.unmatched_rows / counters.selected_rows)
        known_snapshot = (ppd_digest, onspd_digest) in KNOWN_SNAPSHOT_COUNTS
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "processed_at": datetime.now(UTC).isoformat(),
            "sources": {
                "ppd": asdict(SourceFingerprint.from_path(ppd_path, ppd_digest)),
                "onspd": asdict(SourceFingerprint.from_path(onspd_path, onspd_digest)),
                "districts": [
                    asdict(SourceFingerprint.from_path(path, sha256_file(path)))
                    for path in district_paths
                ],
            },
            "filters": {
                "from": MIN_DATE.isoformat(),
                "county": "GREATER LONDON",
                "category": "A",
                "record_status": "A",
                "price": [MIN_PRICE, MAX_PRICE],
                "london_lads": sorted(LONDON_LADS),
            },
            "counts": counters.to_dict(),
            "date_ranges": {
                "source": [counters.source_min_date, counters.source_max_date],
                "final": [counters.final_min_date, counters.final_max_date],
            },
            "join_coverage": coverage,
            "coordinate_bounds": bounds,
            "outputs": {
                "transactions": final_path.name,
                "districts": districts_path.name,
            },
            "district_count": district_count,
        }
        staged_manifest = staging_dir / "source-manifest.json"
        staged_validation = staging_dir / "validation-report.json"
        staged_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staged_validation.write_text(
            json.dumps(
                {
                    "valid": True,
                    "known_snapshot": known_snapshot,
                    "join_coverage": coverage,
                    "counts": counters.to_dict(),
                    "date_ranges": manifest["date_ranges"],
                    "coordinate_bounds": bounds,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        # Publish the manifest last: loaders treat it as the completed-build marker.
        for staged, destination in (
            (temporary_output, final_path),
            (staged_districts, districts_path),
            (staged_validation, validation_path),
            (staged_manifest, manifest_path),
        ):
            os.replace(staged, destination)
    return manifest


def write_json(value: dict[str, Any], target: IO[str]) -> None:
    json.dump(value, target, indent=2, sort_keys=True)
    target.write("\n")

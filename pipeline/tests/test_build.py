from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from pipeline.lpe_pipeline.build import (
    KNOWN_SNAPSHOT_COUNTS,
    PipelineError,
    load_onspd_matches,
    validate_gates,
    write_final,
)
from pipeline.lpe_pipeline.models import BuildCounters


def test_onspd_duplicate_fails(tmp_path: Path) -> None:
    path = tmp_path / "onspd.csv"
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["PCDS", "DOTERM", "LAD25CD", "LAT", "LONG"])
        writer.writeheader()
        row = {
            "PCDS": "SW11 4NB",
            "DOTERM": "",
            "LAD25CD": "E09000032",
            "LAT": "51.47",
            "LONG": "-0.16",
        }
        writer.writerow(row)
        writer.writerow(row)
    with pytest.raises(PipelineError, match="duplicate"):
        load_onspd_matches(path, {"SW114NB"}, BuildCounters())


def test_onspd_duplicate_outside_selected_postcodes_still_fails(tmp_path: Path) -> None:
    path = tmp_path / "onspd.csv"
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["PCDS", "DOTERM", "LAD25CD", "LAT", "LONG"])
        writer.writeheader()
        row = {
            "PCDS": "E8 1AA",
            "DOTERM": "",
            "LAD25CD": "E09000012",
            "LAT": "51.54",
            "LONG": "-0.06",
        }
        writer.writerow(row)
        writer.writerow(row)
    with pytest.raises(PipelineError, match="duplicate"):
        load_onspd_matches(path, {"SW114NB"}, BuildCounters())


def test_write_final_filters_non_london(tmp_path: Path) -> None:
    spool = tmp_path / "spool.csv"
    fields = [
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
    with spool.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "price": "100000",
                "date": "2024-01-01",
                "postcode": "SW11 4NB",
                "district": "SW11",
                "property_type": "F",
                "is_new": "false",
                "tenure": "L",
                "paon": "1",
                "saon": "",
                "street": "HIGH STREET",
                "town": "LONDON",
                "join_key": "SW114NB",
            }
        )
    from pipeline.lpe_pipeline.models import OnspdRecord

    counters = BuildCounters()
    output = tmp_path / "out.csv"
    write_final(
        spool,
        output,
        {"SW114NB": OnspdRecord("SW11 4NB", "E06000001", -0.16, 51.47, None)},
        counters,
    )
    assert counters.outside_london_rows == 1
    assert counters.final_rows == 0


def test_date_ranges_are_recorded() -> None:
    counters = BuildCounters()
    counters.observe_date("source", date(2024, 5, 2))
    counters.observe_date("source", date(1995, 1, 1))
    counters.observe_date("source", date(2026, 4, 30))
    assert counters.source_min_date == "1995-01-01"
    assert counters.source_max_date == "2026-04-30"


def test_exact_snapshot_requires_both_source_hashes() -> None:
    ppd_hash, onspd_hash = next(iter(KNOWN_SNAPSHOT_COUNTS))
    generic = BuildCounters(selected_rows=400_000, final_rows=400_000)
    validate_gates(generic, ppd_hash, "different-onspd-hash")

    with pytest.raises(PipelineError, match="known-snapshot mismatch"):
        validate_gates(generic, ppd_hash, onspd_hash)

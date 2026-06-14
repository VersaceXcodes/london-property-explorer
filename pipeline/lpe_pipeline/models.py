from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class OnspdRecord:
    postcode: str
    lad_code: str
    longitude: float
    latitude: float
    termination_date: str | None


@dataclass(slots=True)
class BuildCounters:
    ppd_rows: int = 0
    malformed_ppd_rows: int = 0
    selected_rows: int = 0
    invalid_postcodes: int = 0
    invalid_prices: int = 0
    invalid_dates: int = 0
    unmatched_rows: int = 0
    outside_london_rows: int = 0
    invalid_coordinate_rows: int = 0
    final_rows: int = 0
    terminated_rows: int = 0
    selected_unique_postcodes: int = 0
    matched_unique_postcodes: int = 0
    final_unique_postcodes: int = 0
    duplicate_onspd_keys: int = 0
    source_min_date: str | None = None
    source_max_date: str | None = None
    final_min_date: str | None = None
    final_max_date: str | None = None
    property_types: dict[str, int] = field(default_factory=dict)
    new_build_codes: dict[str, int] = field(default_factory=dict)
    tenure_codes: dict[str, int] = field(default_factory=dict)

    def increment_domain(self, field_name: str, value: str) -> None:
        domain = getattr(self, field_name)
        domain[value] = domain.get(value, 0) + 1

    def observe_date(self, prefix: str, value: date) -> None:
        encoded = value.isoformat()
        minimum_name = f"{prefix}_min_date"
        maximum_name = f"{prefix}_max_date"
        minimum = getattr(self, minimum_name)
        maximum = getattr(self, maximum_name)
        if minimum is None or encoded < minimum:
            setattr(self, minimum_name, encoded)
        if maximum is None or encoded > maximum:
            setattr(self, maximum_name, encoded)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    basename: str
    bytes: int
    sha256: str

    @classmethod
    def from_path(cls, path: Path, digest: str) -> SourceFingerprint:
        return cls(basename=path.name, bytes=path.stat().st_size, sha256=digest)

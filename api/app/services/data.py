from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from api.app.core.errors import AppError
from api.app.db.repository import Repository
from api.app.models import QueryFilterModel
from pipeline.lpe_pipeline.postcodes import canonical_postcode

WEB_MERCATOR_WORLD_METRES = 40_075_016.686
LOGGER = logging.getLogger("lpe.data")


def cell_size_metres(zoom: int, cell_px: int) -> float:
    return float(WEB_MERCATOR_WORLD_METRES / (2**zoom) / 256 * cell_px)


class DataService:
    def __init__(
        self, repository: Repository, *, max_points: int, cell_px: int, cluster_zoom: int
    ) -> None:
        self.repository = repository
        self.max_points = max_points
        self.cell_px = cell_px
        self.cluster_zoom = cluster_zoom
        self._districts: dict[str, Any] | None = None
        self._meta: dict[str, Any] | None = None

    async def transactions(
        self, bbox: tuple[float, float, float, float], zoom: int, filters: QueryFilterModel
    ) -> tuple[str, list[dict[str, Any]], bool]:
        if zoom < self.cluster_zoom:
            rows = await self.repository.clusters(
                bbox, zoom, self.cell_px, cell_size_metres(zoom, self.cell_px), filters
            )
            return "clusters", rows, False
        if bbox[2] - bbox[0] > 2.0 or bbox[3] - bbox[1] > 2.0:
            raise AppError(400, "BAD_BBOX", "points-mode bbox may not exceed 2 degrees per side")
        rows = await self.repository.points(bbox, filters, self.max_points + 1)
        truncated = len(rows) > self.max_points
        return "points", rows[: self.max_points], truncated

    async def history(self, postcode: str) -> tuple[str, list[dict[str, Any]], bool]:
        try:
            canonical = canonical_postcode(postcode)
        except ValueError as exc:
            raise AppError(400, "BAD_REQUEST", str(exc)) from exc
        rows = await self.repository.postcode_history(canonical)
        if not rows:
            raise AppError(404, "NOT_FOUND", "No transactions found for postcode")
        truncated = len(rows) > 200
        return canonical, rows[:200], truncated

    async def districts(self) -> dict[str, Any]:
        if self._districts is None:
            self._districts = await self.repository.districts()
            size = len(json.dumps(self._districts, separators=(",", ":")).encode("utf-8"))
            if size >= 500 * 1024:
                LOGGER.warning(
                    "district_geojson_payload_exceeds_gate",
                    extra={"payload_bytes": size},
                )
        return self._districts

    async def meta(self) -> dict[str, Any]:
        if self._meta is None:
            self._meta = await self.repository.meta()
        return self._meta


def parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError(400, "BAD_REQUEST", f"invalid ISO date: {value}") from exc

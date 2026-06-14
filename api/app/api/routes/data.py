from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.app.api.dependencies import get_data_service, get_repository
from api.app.core.errors import AppError
from api.app.db.repository import Repository
from api.app.models import (
    ClustersResponse,
    DistrictStats,
    PointsResponse,
    PostcodeHistory,
    QueryFilterModel,
    parse_bbox,
    parse_tenures,
    parse_types,
)
from api.app.services.binary import encode_points
from api.app.services.data import DataService

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/transactions")
async def transactions(
    request: Request,
    service: Annotated[DataService, Depends(get_data_service)],
    bbox: Annotated[str, Query()],
    zoom: Annotated[int, Query(ge=0, le=22)],
    min_price: Annotated[int | None, Query(ge=0, le=50_000_000)] = None,
    max_price: Annotated[int | None, Query(ge=0, le=50_000_000)] = None,
    types: str | None = None,
    tenures: str | None = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    format: Literal["json", "bin"] = "json",
) -> Response:
    try:
        parsed_bbox = parse_bbox(bbox)
        parsed_types = parse_types(types)
        parsed_tenures = parse_tenures(tenures)
        filters = QueryFilterModel(
            min_price=min_price,
            max_price=max_price,
            types=parsed_types,
            tenures=parsed_tenures,
            **{"from": from_date, "to": to_date},
        )
    except ValueError as exc:
        raise AppError(400, "BAD_REQUEST", str(exc)) from exc
    mode, rows, truncated = await service.transactions(parsed_bbox, zoom, filters)
    request.state.response_mode = mode
    request.state.response_count = len(rows)
    if mode == "clusters":
        cluster_body = ClustersResponse(cells=rows)
        return JSONResponse(
            content=cluster_body.model_dump(mode="json"),
            headers={"Cache-Control": "public, max-age=3600"},
        )
    if format == "bin":
        return Response(
            content=encode_points(rows),
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Truncated": str(truncated).lower(),
            },
        )
    points_body = PointsResponse(truncated=truncated, points=rows)
    return JSONResponse(
        content=points_body.model_dump(mode="json"),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/districts")
async def districts(service: Annotated[DataService, Depends(get_data_service)]) -> JSONResponse:
    return JSONResponse(
        content=await service.districts(),
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/district-stats", response_model=list[DistrictStats])
async def district_stats(
    repository: Annotated[Repository, Depends(get_repository)], response: Response
) -> list[DistrictStats]:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return [DistrictStats.model_validate(row) for row in await repository.district_stats()]


@router.get("/postcode/{postcode}/history", response_model=PostcodeHistory)
async def postcode_history(
    postcode: str,
    service: Annotated[DataService, Depends(get_data_service)],
    response: Response,
) -> PostcodeHistory:
    canonical, entries, truncated = await service.history(postcode)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return PostcodeHistory(
        postcode=canonical, count=len(entries), truncated=truncated, entries=entries
    )

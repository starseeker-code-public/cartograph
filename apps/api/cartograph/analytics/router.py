"""Coverage analytics (Phase 8): order density on an H3 hex grid.

Resolution is selectable 7–9. Orders store precomputed res-8 cells
(``pickup_h3_8`` / ``delivery_h3_8``) for DB-side rollups; this endpoint
recomputes cells from the raw points in Python so any of the three
resolutions is exact (res 9 is finer than the stored res 8 and can't be
derived from it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

import h3
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


class CoverageCell(BaseModel):
    hex: str
    count: int


class CoverageResponse(BaseModel):
    resolution: int
    kind: Literal["pickup", "delivery"]
    total_orders: int
    cells: list[CoverageCell]


@router.get("/coverage", response_model=CoverageResponse)
async def coverage(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    resolution: Annotated[int, Query(ge=7, le=9)] = 8,
    kind: Annotated[Literal["pickup", "delivery"], Query()] = "pickup",
) -> CoverageResponse:
    column = "pickup" if kind == "pickup" else "delivery"
    clauses = ["tenant_id = :tenant"]
    params: dict[str, object] = {"tenant": current.tenant_id}
    if from_ is not None:
        clauses.append("created_at >= :from_ts")
        params["from_ts"] = from_
    if to is not None:
        clauses.append("created_at < :to_ts")
        params["to_ts"] = to

    rows = (
        await db.execute(
            text(
                f"SELECT ST_X({column}::geometry) AS lng, ST_Y({column}::geometry) AS lat "  # noqa: S608
                f"FROM orders WHERE {' AND '.join(clauses)}"
            ),
            params,
        )
    ).all()

    counts: dict[str, int] = {}
    for row in rows:
        cell = h3.latlng_to_cell(row.lat, row.lng, resolution)
        counts[cell] = counts.get(cell, 0) + 1

    cells = [
        CoverageCell(hex=hex_id, count=count)
        for hex_id, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return CoverageResponse(resolution=resolution, kind=kind, total_orders=len(rows), cells=cells)

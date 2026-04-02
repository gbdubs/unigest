from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_db
from server.models import ExtractorResponse, ExtractorRow

router = APIRouter(prefix="/extractors", tags=["extractors"])


@router.get("")
async def list_extractors(
    domain: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ExtractorResponse]:
    stmt = select(ExtractorRow)
    if domain:
        stmt = stmt.where(ExtractorRow.domain == domain)
    if status:
        stmt = stmt.where(ExtractorRow.status == status)
    stmt = stmt.order_by(ExtractorRow.created_at.desc())

    result = await db.execute(stmt)
    return [
        ExtractorResponse(
            id=e.id,
            domain=e.domain,
            name=e.name,
            code=e.code,
            config=e.config or {},
            status=e.status,
            success_count=e.success_count,
            failure_count=e.failure_count,
            created_at=e.created_at,
        )
        for e in result.scalars().all()
    ]


@router.get("/{extractor_id}")
async def get_extractor(
    extractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ExtractorResponse:
    e = await db.get(ExtractorRow, extractor_id)
    if not e:
        raise HTTPException(404, "Extractor not found")
    return ExtractorResponse(
        id=e.id,
        domain=e.domain,
        name=e.name,
        code=e.code,
        config=e.config or {},
        status=e.status,
        success_count=e.success_count,
        failure_count=e.failure_count,
        created_at=e.created_at,
    )


@router.post("/{extractor_id}/disable")
async def disable_extractor(
    extractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    e = await db.get(ExtractorRow, extractor_id)
    if not e:
        raise HTTPException(404, "Extractor not found")
    e.status = "disabled"
    await db.commit()
    return {"status": "disabled"}

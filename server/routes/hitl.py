from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_db
from server.models import HITLCompleteRequest, HITLRequestRow, HITLResponse, JobRow

router = APIRouter(prefix="/hitl", tags=["hitl"])


@router.get("/pending")
async def list_pending(db: AsyncSession = Depends(get_db)) -> list[HITLResponse]:
    result = await db.execute(
        select(HITLRequestRow)
        .where(HITLRequestRow.status == "pending")
        .order_by(HITLRequestRow.created_at)
    )
    return [
        HITLResponse(
            id=r.id,
            job_id=r.job_id,
            request_type=r.request_type,
            instructions=r.instructions,
            target_url=r.target_url,
            expires_at=r.expires_at,
        )
        for r in result.scalars().all()
    ]


@router.post("/{hitl_id}/complete")
async def complete_hitl(
    hitl_id: uuid.UUID,
    body: HITLCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    hitl = await db.get(HITLRequestRow, hitl_id)
    if not hitl:
        raise HTTPException(404, "HITL request not found")

    now = datetime.now(timezone.utc)
    hitl.status = "completed"
    hitl.response_data = body.response_data
    hitl.completed_at = now

    # Re-queue the original job for retry
    job = await db.get(JobRow, hitl.job_id)
    if job:
        job.status = "pending"
        job.updated_at = now

    await db.commit()
    return {"status": "ok"}

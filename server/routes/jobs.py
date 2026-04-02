from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_db
from server.models import (
    FlagRequest,
    JobCreate,
    JobResponse,
    JobRow,
    ResultResponse,
    ResultRow,
)
from shared.hashing import content_hash, url_hash

router = APIRouter(tags=["jobs"])


def _compute_hash(body: JobCreate) -> str:
    if body.input_type == "url":
        return url_hash(body.input_value)
    elif body.input_type == "base64":
        return content_hash(base64.b64decode(body.input_value))
    else:  # blob
        return content_hash(body.input_value.encode())


@router.post("/jobs", status_code=201)
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)) -> JobResponse:
    h = _compute_hash(body)

    # Check cache
    if not body.force_refresh:
        result = await db.execute(
            select(ResultRow).where(ResultRow.content_hash == h, ResultRow.flagged == False)  # noqa: E712
        )
        cached = result.scalar_one_or_none()
        if cached:
            job = JobRow(
                input_type=body.input_type,
                input_value=body.input_value,
                content_hash=h,
                mime_type=body.mime_type,
                webhook_url=body.webhook_url,
                status="completed",
                result_id=cached.id,
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return JobResponse(
                job_id=job.id,
                status="completed",
                cached=True,
                input_type=job.input_type,
                created_at=job.created_at,
                completed_at=job.created_at,
                result=ResultResponse(
                    extracted_text=cached.extracted_text,
                    metadata=cached.metadata_ or {},
                    quality_score=cached.quality_score,
                    extraction_strategy=cached.extraction_strategy,
                ),
            )

    job = JobRow(
        input_type=body.input_type,
        input_value=body.input_value,
        content_hash=h,
        mime_type=body.mime_type,
        webhook_url=body.webhook_url,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return JobResponse(job_id=job.id, status="pending", input_type=job.input_type, created_at=job.created_at)


@router.get("/jobs/{job_id}")
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobResponse:
    job = await db.get(JobRow, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    result = None
    if job.result:
        result = ResultResponse(
            extracted_text=job.result.extracted_text,
            metadata=job.result.metadata_ or {},
            quality_score=job.result.quality_score,
            extraction_strategy=job.result.extraction_strategy,
        )

    return JobResponse(
        job_id=job.id,
        status=job.status,
        input_type=job.input_type,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result,
        error=job.error_message,
    )


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ResultResponse:
    job = await db.get(JobRow, job_id)
    if not job or job.status != "completed" or not job.result:
        raise HTTPException(404, "Result not found")
    return ResultResponse(
        extracted_text=job.result.extracted_text,
        metadata=job.result.metadata_ or {},
        quality_score=job.result.quality_score,
        extraction_strategy=job.result.extraction_strategy,
    )


@router.post("/jobs/{job_id}/flag")
async def flag_job(job_id: uuid.UUID, body: FlagRequest, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobRow, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Flag the existing result
    if job.result_id:
        result = await db.get(ResultRow, job.result_id)
        if result:
            result.flagged = True

    # Create a new job for re-extraction
    new_job = JobRow(
        input_type=job.input_type,
        input_value=job.input_value,
        content_hash=job.content_hash,
        mime_type=job.mime_type,
        webhook_url=job.webhook_url,
    )
    db.add(new_job)
    await db.commit()
    return {"status": "flagged", "new_job_id": str(new_job.id)}

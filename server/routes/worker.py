from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_db
from server.models import (
    ExtractionLogRow,
    HITLCreateRequest,
    HITLRequestRow,
    JobRow,
    ResultRow,
    WorkerFailSubmit,
    WorkerResultSubmit,
)
from server.webhook import dispatch_webhook

router = APIRouter(prefix="/worker", tags=["worker"])


@router.get("/jobs")
async def claim_jobs(
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    # SELECT FOR UPDATE SKIP LOCKED to atomically claim jobs
    stmt = (
        select(JobRow)
        .where(JobRow.status == "pending")
        .order_by(JobRow.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    jobs = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "processing"
        job.started_at = now
        job.updated_at = now

    await db.commit()

    return [
        {
            "job_id": str(job.id),
            "input_type": job.input_type,
            "input_value": job.input_value,
            "content_hash": job.content_hash,
            "mime_type": job.mime_type,
        }
        for job in jobs
    ]


@router.post("/jobs/{job_id}/result")
async def submit_result(
    job_id: uuid.UUID,
    body: WorkerResultSubmit,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(JobRow, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    now = datetime.now(timezone.utc)

    # Check for existing result with same content hash (e.g. force_refresh or retry)
    existing = None
    if job.content_hash:
        stmt = select(ResultRow).where(ResultRow.content_hash == job.content_hash)
        existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        # Update the existing result
        existing.extracted_text = body.extracted_text
        existing.metadata_ = body.metadata
        existing.quality_score = body.quality_score
        existing.extraction_strategy = body.extraction_strategy
        existing.flagged = False
        result = existing
    else:
        result = ResultRow(
            content_hash=job.content_hash or str(uuid.uuid4()),
            extracted_text=body.extracted_text,
            metadata_=body.metadata,
            quality_score=body.quality_score,
            extraction_strategy=body.extraction_strategy,
        )
        db.add(result)
        await db.flush()

    # Update job
    job.status = "completed"
    job.result_id = result.id
    job.completed_at = now
    job.updated_at = now

    # Save logs
    for log in body.logs:
        db.add(ExtractionLogRow(
            job_id=job_id,
            stage=log.stage,
            success=log.success,
            quality_score=log.quality_score,
            duration_ms=log.duration_ms,
            error_type=log.error_type,
            error_detail=log.error_detail,
            extractor_id=log.extractor_id,
        ))

    await db.commit()

    # Dispatch webhook
    if job.webhook_url:
        await dispatch_webhook(
            job.webhook_url,
            job_id=str(job.id),
            status="completed",
            result={
                "extracted_text": body.extracted_text,
                "metadata": body.metadata,
                "quality_score": body.quality_score,
            },
        )

    return {"status": "ok"}


@router.post("/jobs/{job_id}/fail")
async def submit_failure(
    job_id: uuid.UUID,
    body: WorkerFailSubmit,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(JobRow, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    now = datetime.now(timezone.utc)
    job.status = "failed"
    job.error_message = f"{body.error_type}: {body.error_detail}"
    job.completed_at = now
    job.updated_at = now

    for log in body.logs:
        db.add(ExtractionLogRow(
            job_id=job_id,
            stage=log.stage,
            success=log.success,
            quality_score=log.quality_score,
            duration_ms=log.duration_ms,
            error_type=log.error_type,
            error_detail=log.error_detail,
            extractor_id=log.extractor_id,
        ))

    await db.commit()

    if job.webhook_url:
        await dispatch_webhook(
            job.webhook_url,
            job_id=str(job.id),
            status="failed",
            error={"type": body.error_type, "detail": body.error_detail},
        )

    return {"status": "ok"}


@router.post("/jobs/{job_id}/hitl")
async def request_hitl(
    job_id: uuid.UUID,
    body: HITLCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(JobRow, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    now = datetime.now(timezone.utc)
    job.status = "needs_hitl"
    job.updated_at = now

    hitl = HITLRequestRow(
        job_id=job_id,
        request_type=body.request_type,
        instructions=body.instructions,
        target_url=body.target_url,
        expires_at=now + timedelta(hours=24),
    )
    db.add(hitl)
    await db.commit()

    return {"status": "ok", "hitl_id": str(hitl.id)}

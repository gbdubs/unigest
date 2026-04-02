from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Real,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


# ── SQLAlchemy ORM ──────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, nullable=False, default="pending")
    input_type = Column(String, nullable=False)
    input_value = Column(Text, nullable=False)
    content_hash = Column(String)
    mime_type = Column(String)
    webhook_url = Column(String)
    result_id = Column(UUID(as_uuid=True), ForeignKey("results.id"))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    result = relationship("ResultRow", foreign_keys=[result_id], lazy="selectin")

    __table_args__ = (
        Index("idx_jobs_status", "status", "created_at"),
        Index("idx_jobs_content_hash", "content_hash"),
    )


class ResultRow(Base):
    __tablename__ = "results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_hash = Column(String, nullable=False)
    extracted_text = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    quality_score = Column(Real)
    extraction_strategy = Column(String, nullable=False)
    extractor_id = Column(UUID(as_uuid=True), ForeignKey("extractors.id"))
    flagged = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_results_content_hash", "content_hash", unique=True),
    )


class ExtractorRow(Base):
    __tablename__ = "extractors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String, nullable=False)
    name = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    status = Column(String, nullable=False, default="candidate")
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    promoted_at = Column(DateTime(timezone=True))
    parent_id = Column(UUID(as_uuid=True), ForeignKey("extractors.id"))

    __table_args__ = (
        Index("idx_extractors_domain", "domain", "status"),
    )


class ExtractionLogRow(Base):
    __tablename__ = "extraction_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    stage = Column(String, nullable=False)
    extractor_id = Column(UUID(as_uuid=True), ForeignKey("extractors.id"))
    success = Column(Boolean, nullable=False)
    quality_score = Column(Real)
    duration_ms = Column(Integer)
    error_type = Column(String)
    error_detail = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_extraction_logs_job", "job_id"),
        Index("idx_extraction_logs_error", "error_type", "created_at"),
    )


class HITLRequestRow(Base):
    __tablename__ = "hitl_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    request_type = Column(String, nullable=False)
    instructions = Column(Text, nullable=False)
    target_url = Column(String)
    status = Column(String, nullable=False, default="pending")
    response_data = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_hitl_status", "status", "created_at"),
    )


# ── Pydantic schemas ────────────────────────────────────────────


class JobCreate(BaseModel):
    input_type: str  # url | blob | base64
    input_value: str
    mime_type: str | None = None
    webhook_url: str | None = None
    force_refresh: bool = False


class JobResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    cached: bool = False
    input_type: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ResultResponse | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


class ResultResponse(BaseModel):
    extracted_text: str
    metadata: dict[str, Any] = {}
    quality_score: float | None = None
    extraction_strategy: str

    model_config = {"from_attributes": True}


class FlagRequest(BaseModel):
    reason: str  # missing_content | wrong_content | garbled | other
    detail: str = ""


class LogEntry(BaseModel):
    stage: str
    success: bool
    duration_ms: int | None = None
    quality_score: float | None = None
    error_type: str | None = None
    error_detail: str | None = None
    extractor_id: uuid.UUID | None = None


class WorkerResultSubmit(BaseModel):
    extracted_text: str
    metadata: dict[str, Any] = {}
    quality_score: float | None = None
    extraction_strategy: str
    logs: list[LogEntry] = []


class WorkerFailSubmit(BaseModel):
    error_type: str
    error_detail: str = ""
    logs: list[LogEntry] = []


class HITLCreateRequest(BaseModel):
    request_type: str
    instructions: str
    target_url: str | None = None


class HITLCompleteRequest(BaseModel):
    response_data: str


class HITLResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    request_type: str
    instructions: str
    target_url: str | None = None
    expires_at: datetime

    model_config = {"from_attributes": True}


class ExtractorResponse(BaseModel):
    id: uuid.UUID
    domain: str
    name: str
    code: str
    config: dict[str, Any] = {}
    status: str
    success_count: int
    failure_count: int
    created_at: datetime

    model_config = {"from_attributes": True}

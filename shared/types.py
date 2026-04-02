from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_HITL = "needs_hitl"


class ExtractionStage(StrEnum):
    CACHE = "cache"
    DOMAIN_EXTRACTOR = "domain_extractor"
    GENERIC = "generic"
    HEADLESS = "headless"
    LLM_ASSISTED = "llm_assisted"
    HITL = "hitl"


@dataclass
class ExtractionResult:
    text: str
    metadata: dict = field(default_factory=dict)
    quality_score: float | None = None


class ExtractionError(Exception):
    def __init__(self, error_type: str, detail: str = ""):
        self.error_type = error_type
        self.detail = detail
        super().__init__(f"{error_type}: {detail}")


class NeedsHITLError(ExtractionError):
    """Raised when human-in-the-loop intervention is needed."""

    def __init__(self, request_type: str, instructions: str, target_url: str | None = None):
        self.request_type = request_type
        self.instructions = instructions
        self.target_url = target_url
        super().__init__("needs_hitl", instructions)

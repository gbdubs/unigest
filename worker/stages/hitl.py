from __future__ import annotations

import logging

import httpx

from shared.types import ExtractionResult, NeedsHITLError
from worker.config import get_settings

logger = logging.getLogger("unigest.stages.hitl")


async def request_hitl(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 6: Request human-in-the-loop assistance."""
    job_id = job["job_id"]
    url = job.get("input_value", "")
    settings = get_settings()

    logger.info("Requesting HITL for job %s", job_id)

    await http_client.post(
        f"{settings.SERVER_URL}/worker/jobs/{job_id}/hitl",
        json={
            "request_type": "manual_extraction",
            "instructions": (
                "All automated extraction methods failed for this content. "
                "Please manually extract the text content."
            ),
            "target_url": url if job.get("input_type") == "url" else None,
        },
    )

    raise NeedsHITLError(
        request_type="manual_extraction",
        instructions="Waiting for human assistance",
        target_url=url,
    )

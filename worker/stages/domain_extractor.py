from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from shared.types import ExtractionError, ExtractionResult
from worker.config import get_settings
from worker.sandbox import run_in_sandbox

logger = logging.getLogger("unigest.stages.domain_extractor")


async def run_domain_extractor(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 2: Run a learned domain-specific extractor if one exists."""
    if job.get("input_type") != "url":
        return None

    url = job["input_value"]
    domain = urlparse(url).netloc

    settings = get_settings()
    resp = await http_client.get(
        f"{settings.SERVER_URL}/extractors",
        params={"domain": domain, "status": "trusted"},
    )

    if resp.status_code != 200:
        return None

    extractors = resp.json()
    if not extractors:
        return None

    # Try the most recently created trusted extractor
    extractor = extractors[0]
    logger.info("Running domain extractor '%s' for %s", extractor["name"], domain)

    try:
        result = await run_in_sandbox(
            code=extractor["code"],
            url=url,
            timeout=settings.SANDBOX_TIMEOUT_SECONDS,
            memory_mb=settings.SANDBOX_MEMORY_MB,
        )
        return result
    except Exception as exc:
        logger.warning("Domain extractor '%s' failed: %s", extractor["name"], exc)
        raise ExtractionError("domain_extractor_failed", str(exc))

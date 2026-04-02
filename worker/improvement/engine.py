from __future__ import annotations

import logging
import time
from collections import deque
from urllib.parse import urlparse

import httpx

from shared.types import ExtractionResult
from worker.config import get_settings
from worker.improvement.codegen import generate_extractor
from worker.improvement.diagnosis import diagnose_failure
from worker.quality import check_quality
from worker.sandbox import run_in_sandbox

logger = logging.getLogger("unigest.improvement")

# Rate limiting: track timestamps of recent improvement cycles
_recent_cycles: deque[float] = deque()


def _check_rate_limit() -> bool:
    settings = get_settings()
    now = time.time()
    cutoff = now - 3600  # 1 hour window
    while _recent_cycles and _recent_cycles[0] < cutoff:
        _recent_cycles.popleft()
    return len(_recent_cycles) < settings.IMPROVEMENT_RATE_LIMIT


async def run_improvement(
    job: dict,
    logs: list[dict],
    http_client: httpx.AsyncClient,
) -> ExtractionResult | None:
    """Attempt to create a new extractor after pipeline failure."""
    if not _check_rate_limit():
        logger.warning("Improvement rate limit reached, skipping")
        return None

    _recent_cycles.append(time.time())
    settings = get_settings()

    # Step 1: Diagnose
    diagnosis = await diagnose_failure(job, logs, http_client, settings)
    if not diagnosis:
        return None

    # Step 2: Generate extractor code
    code = await generate_extractor(diagnosis, job, http_client, settings)
    if not code:
        return None

    # Step 3: Test in sandbox
    url = job.get("input_value", "")
    try:
        result = await run_in_sandbox(
            code=code,
            url=url,
            timeout=settings.SANDBOX_TIMEOUT_SECONDS,
            memory_mb=settings.SANDBOX_MEMORY_MB,
        )
    except Exception as exc:
        logger.warning("Generated extractor failed sandbox test: %s", exc)
        return None

    # Step 4: Validate quality
    score = check_quality(result.text, job.get("input_type", "url"))
    if score < 0.6:
        logger.info("Generated extractor quality too low (%.2f)", score)
        return None

    result.quality_score = score

    # Step 5: Save as candidate extractor
    domain = urlparse(url).netloc if job.get("input_type") == "url" else "*"
    await http_client.post(
        f"{settings.SERVER_URL}/extractors",
        json={
            "domain": domain,
            "name": f"auto-generated for {domain}",
            "code": code,
            "config": {},
            "status": "candidate",
        },
    )

    logger.info("Created candidate extractor for %s (quality=%.2f)", domain, score)
    return result

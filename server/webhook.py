from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from server.config import get_settings

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 5, 25]  # seconds


async def dispatch_webhook(
    webhook_url: str,
    *,
    job_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget webhook with retries."""
    settings = get_settings()
    payload = {
        "job_id": job_id,
        "status": status,
        "result": result,
        "error": error,
    }

    async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
        for attempt, delay in enumerate([0] + RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.post(webhook_url, json=payload)
                if 200 <= resp.status_code < 300:
                    logger.info("Webhook delivered to %s (attempt %d)", webhook_url, attempt + 1)
                    return
                logger.warning(
                    "Webhook to %s returned %d (attempt %d)", webhook_url, resp.status_code, attempt + 1
                )
            except httpx.HTTPError as exc:
                logger.warning("Webhook to %s failed (attempt %d): %s", webhook_url, attempt + 1, exc)

    logger.error("Webhook delivery to %s exhausted all retries", webhook_url)

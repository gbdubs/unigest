from __future__ import annotations

import logging

import httpx

from worker.config import get_settings

logger = logging.getLogger("unigest.improvement.review")


async def periodic_review(http_client: httpx.AsyncClient) -> None:
    """Review extraction logs for common failure patterns and propose generic improvements.

    This should be called on a schedule (e.g., daily via cron or a background task).
    """
    settings = get_settings()

    # Query server for common failure patterns (hypothetical endpoint)
    # In practice, this would use a direct DB query or a dedicated analytics endpoint
    try:
        resp = await http_client.get(
            f"{settings.SERVER_URL}/extractors",
            params={"status": "candidate"},
        )
        if resp.status_code != 200:
            return

        candidates = resp.json()

        # Promote extractors that have enough successes
        for ext in candidates:
            if ext.get("success_count", 0) >= 3 and ext.get("failure_count", 0) == 0:
                # Check if it's a generic improvement (needs higher threshold)
                if ext.get("domain") == "*":
                    # Generic: need 5 successes across 3+ domains
                    if ext.get("success_count", 0) < 5:
                        continue

                logger.info("Promoting extractor %s (%s)", ext["id"], ext["name"])
                await http_client.post(
                    f"{settings.SERVER_URL}/extractors/{ext['id']}/promote",
                )

    except Exception as exc:
        logger.warning("Periodic review failed: %s", exc)

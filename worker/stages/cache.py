from __future__ import annotations

import httpx

from shared.types import ExtractionResult


async def check_cache(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 1: Cache lookup.

    The server already checks cache at job submission time. If we got here,
    the job wasn't cached. Return None to skip to the next stage.
    """
    return None

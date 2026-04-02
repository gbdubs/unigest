from __future__ import annotations

import logging

import httpx

from shared.types import ExtractionError, ExtractionResult
from worker.config import get_settings

logger = logging.getLogger("unigest.stages.llm_assisted")


async def run_llm_assisted(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 5: LLM-assisted extraction via Ollama."""
    if job.get("input_type") != "url":
        return None

    url = job["input_value"]
    settings = get_settings()

    # First, get the page HTML (try headless if available)
    try:
        resp = await http_client.get(url, follow_redirects=True, timeout=15)
        html = resp.text
    except Exception as exc:
        raise ExtractionError("fetch_failed", str(exc))

    # Truncate HTML to avoid overwhelming the LLM
    max_chars = 50000
    if len(html) > max_chars:
        html = html[:max_chars] + "\n... [truncated]"

    prompt = (
        f"The following HTML is from {url}. Extract the main text content, "
        "removing navigation, ads, footers, and other boilerplate. "
        "Return only the article/document text, preserving paragraph structure.\n\n"
        f"{html}"
    )

    try:
        llm_resp = await http_client.post(
            f"{settings.LLM_ENDPOINT}/api/generate",
            json={
                "model": settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        llm_resp.raise_for_status()
        data = llm_resp.json()
        text = data.get("response", "").strip()

        if not text:
            raise ExtractionError("llm_empty", "LLM returned empty response")

        return ExtractionResult(
            text=text,
            metadata={"source_url": url, "extraction_method": "llm_assisted"},
        )

    except httpx.HTTPError as exc:
        raise ExtractionError("llm_error", str(exc))

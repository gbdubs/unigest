from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger("unigest.improvement.codegen")


async def generate_extractor(
    diagnosis: str,
    job: dict,
    http_client: httpx.AsyncClient,
    settings,
) -> str | None:
    """Ask the LLM to generate extractor code."""
    url = job.get("input_value", "unknown")

    prompt = (
        f"Based on this diagnosis:\n{diagnosis}\n\n"
        f"Write a Python async function with this exact signature:\n\n"
        f"async def extract(url: str, http_client, browser) -> ExtractionResult:\n"
        f'    """Extract content from {url}."""\n\n'
        f"The function should:\n"
        f"1. Use http_client (an httpx.AsyncClient) to fetch the page\n"
        f"2. Parse and extract the main content\n"
        f"3. Return an ExtractionResult(text=str, metadata=dict)\n\n"
        f"Import ExtractionResult from shared.types at the top.\n"
        f"Only output the Python code, no explanation."
    )

    try:
        resp = await http_client.post(
            f"{settings.LLM_ENDPOINT}/api/generate",
            json={
                "model": settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()

        # Extract code from markdown code blocks if present
        code_match = re.search(r"```python\n(.*?)```", raw, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        # If no code blocks, assume the entire response is code
        if "async def extract" in raw:
            return raw

        logger.warning("LLM did not produce valid extractor code")
        return None

    except Exception as exc:
        logger.warning("Codegen LLM call failed: %s", exc)
        return None

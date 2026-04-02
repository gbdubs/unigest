from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("unigest.improvement.diagnosis")


async def diagnose_failure(
    job: dict,
    logs: list[dict],
    http_client: httpx.AsyncClient,
    settings,
) -> str | None:
    """Send failure info to LLM and get a diagnosis."""
    url = job.get("input_value", "unknown")
    input_type = job.get("input_type", "unknown")

    attempts = []
    for log in logs:
        stage = log.get("stage", "unknown")
        error = log.get("error_type", "none")
        detail = log.get("error_detail", "")
        attempts.append(f"- {stage}: {error} — {detail}")

    prompt = (
        f"URL: {url}\n"
        f"Input type: {input_type}\n"
        f"Attempts:\n" + "\n".join(attempts) + "\n\n"
        "Diagnose why extraction failed and propose a fix. "
        "Be specific about what the extractor should do differently."
    )

    try:
        resp = await http_client.post(
            f"{settings.LLM_ENDPOINT}/api/generate",
            json={
                "model": settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.warning("Diagnosis LLM call failed: %s", exc)
        return None

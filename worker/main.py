from __future__ import annotations

import asyncio
import logging
import signal
import sys

import httpx

from worker.config import get_settings
from worker.pipeline import run_pipeline

logger = logging.getLogger("unigest.worker")
_shutdown = asyncio.Event()


def _handle_signal(*_):
    logger.info("Shutdown signal received")
    _shutdown.set()


async def process_job(job: dict, client: httpx.AsyncClient, settings) -> None:
    job_id = job["job_id"]
    logger.info("Processing job %s (%s)", job_id, job.get("input_type"))

    try:
        result, logs = await run_pipeline(job, client)
        await client.post(
            f"{settings.SERVER_URL}/worker/jobs/{job_id}/result",
            json={
                "extracted_text": result.text,
                "metadata": result.metadata,
                "quality_score": result.quality_score,
                "extraction_strategy": logs[-1].get("stage", "unknown") if logs else "unknown",
                "logs": logs,
            },
        )
        logger.info("Job %s completed (score=%.2f)", job_id, result.quality_score or 0)

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await client.post(
            f"{settings.SERVER_URL}/worker/jobs/{job_id}/fail",
            json={
                "error_type": getattr(exc, "error_type", "unknown"),
                "error_detail": str(exc),
                "logs": [],
            },
        )


async def poll_loop() -> None:
    settings = get_settings()
    headers = {}
    if settings.WORKER_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {settings.WORKER_AUTH_TOKEN}"

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        while not _shutdown.is_set():
            try:
                resp = await client.get(
                    f"{settings.SERVER_URL}/worker/jobs",
                    params={"limit": settings.MAX_CONCURRENT_JOBS},
                )
                resp.raise_for_status()
                jobs = resp.json()

                for job in jobs:
                    await process_job(job, client, settings)

            except httpx.HTTPError as exc:
                logger.warning("Poll error: %s", exc)
            except Exception:
                logger.exception("Unexpected poll error")

            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.POLL_INTERVAL_SECONDS)
                break  # shutdown signaled
            except asyncio.TimeoutError:
                pass  # poll again


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    try:
        loop.run_until_complete(poll_loop())
    finally:
        loop.close()
    logger.info("Worker shut down")


if __name__ == "__main__":
    main()

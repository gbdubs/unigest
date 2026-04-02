from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from shared.types import ExtractionError, ExtractionResult, ExtractionStage, NeedsHITLError
from worker.quality import check_quality
from worker.stages.cache import check_cache
from worker.stages.domain_extractor import run_domain_extractor
from worker.stages.generic import run_generic
from worker.stages.headless import run_headless
from worker.stages.llm_assisted import run_llm_assisted
from worker.stages.hitl import request_hitl

logger = logging.getLogger("unigest.pipeline")

QUALITY_THRESHOLD = 0.3

# Ordered stages
STAGES: list[tuple[ExtractionStage, Any]] = [
    (ExtractionStage.CACHE, check_cache),
    (ExtractionStage.DOMAIN_EXTRACTOR, run_domain_extractor),
    (ExtractionStage.GENERIC, run_generic),
    (ExtractionStage.HEADLESS, run_headless),
    (ExtractionStage.LLM_ASSISTED, run_llm_assisted),
    (ExtractionStage.HITL, request_hitl),
]


async def run_pipeline(
    job: dict,
    http_client: httpx.AsyncClient,
) -> tuple[ExtractionResult, list[dict]]:
    """Run the extraction waterfall. Returns (result, logs)."""
    logs: list[dict] = []
    input_type = job.get("input_type", "url")

    for stage_name, stage_fn in STAGES:
        t0 = time.monotonic()
        log_entry = {"stage": stage_name, "success": False}

        try:
            result = await stage_fn(job, http_client)
            if result is None:
                # Stage chose to skip
                continue

            duration_ms = int((time.monotonic() - t0) * 1000)
            log_entry["duration_ms"] = duration_ms

            # Quality check
            score = check_quality(result.text, input_type)
            result.quality_score = score
            log_entry["quality_score"] = score

            if score < QUALITY_THRESHOLD:
                log_entry["error_type"] = "low_quality"
                log_entry["error_detail"] = f"Score {score:.2f} below threshold {QUALITY_THRESHOLD}"
                logs.append(log_entry)
                logger.info("Stage %s produced low quality (%.2f), continuing", stage_name, score)
                continue

            log_entry["success"] = True
            logs.append(log_entry)
            logger.info("Stage %s succeeded (score=%.2f)", stage_name, score)
            return result, logs

        except NeedsHITLError:
            log_entry["error_type"] = "needs_hitl"
            logs.append(log_entry)
            raise

        except ExtractionError as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            log_entry["duration_ms"] = duration_ms
            log_entry["error_type"] = exc.error_type
            log_entry["error_detail"] = exc.detail
            logs.append(log_entry)
            logger.info("Stage %s failed: %s", stage_name, exc)

        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            log_entry["duration_ms"] = duration_ms
            log_entry["error_type"] = "internal_error"
            log_entry["error_detail"] = str(exc)
            logs.append(log_entry)
            logger.exception("Stage %s raised unexpected error", stage_name)

    # All stages exhausted
    raise ExtractionError("all_stages_failed", "No extraction stage produced acceptable results")

from __future__ import annotations

import logging

import httpx

from shared.types import ExtractionError, ExtractionResult
from worker.extractors.html import extract_html

logger = logging.getLogger("unigest.stages.headless")


async def run_headless(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 4: Headless browser extraction with Playwright."""
    if job.get("input_type") != "url":
        return None

    url = job["input_value"]
    logger.info("Launching headless browser for %s", url)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ExtractionError("missing_dependency", "playwright not installed")

    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
    except ImportError:
        stealth = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            if stealth:
                await stealth.apply_stealth_async(page)

            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for any late JS rendering
            await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        return extract_html(html, url)

    except Exception as exc:
        raise ExtractionError("headless_failed", str(exc))

from __future__ import annotations

import base64
import logging

import httpx

from shared.types import ExtractionError, ExtractionResult
from worker.extractors.html import extract_html
from worker.extractors.pdf import extract_pdf
from worker.extractors.docx import extract_docx
from worker.extractors.xlsx import extract_xlsx
from worker.extractors.image import extract_image

logger = logging.getLogger("unigest.stages.generic")


async def run_generic(job: dict, http_client: httpx.AsyncClient) -> ExtractionResult | None:
    """Stage 3: Generic extraction based on content type."""
    input_type = job.get("input_type")
    input_value = job.get("input_value", "")
    mime_type = job.get("mime_type", "")

    if input_type == "url":
        return await _extract_url(input_value, http_client)
    elif input_type == "base64":
        data = base64.b64decode(input_value)
        return _extract_bytes(data, mime_type)
    elif input_type == "blob":
        data = input_value.encode()
        return _extract_bytes(data, mime_type)

    return None


async def _extract_url(url: str, http_client: httpx.AsyncClient) -> ExtractionResult:
    """Fetch URL and extract content."""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession() as s:
            resp = await s.get(url, impersonate="chrome")
            html = resp.text
            content_type = resp.headers.get("content-type", "")
    except Exception:
        # Fallback to httpx
        logger.info("curl_cffi failed, falling back to httpx")
        resp = await http_client.get(url, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        content_type = resp.headers.get("content-type", "")

    if "application/pdf" in content_type:
        return extract_pdf(resp.content)
    if "application/vnd.openxmlformats-officedocument.wordprocessingml" in content_type:
        return extract_docx(resp.content)
    if "application/vnd.openxmlformats-officedocument.spreadsheetml" in content_type:
        return extract_xlsx(resp.content)
    if content_type.startswith("image/"):
        return extract_image(resp.content)

    # Default: treat as HTML
    return extract_html(html, url)


def _extract_bytes(data: bytes, mime_type: str) -> ExtractionResult:
    """Extract content from raw bytes based on MIME type."""
    mime = mime_type.lower() if mime_type else ""

    if "pdf" in mime:
        return extract_pdf(data)
    elif "wordprocessingml" in mime or "docx" in mime:
        return extract_docx(data)
    elif "spreadsheetml" in mime or "xlsx" in mime:
        return extract_xlsx(data)
    elif mime.startswith("image/"):
        return extract_image(data)
    elif "text/" in mime or not mime:
        # Try as plain text
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        return ExtractionResult(text=text, metadata={"mime_type": mime})

    raise ExtractionError("unsupported_type", f"Cannot extract from MIME type: {mime}")

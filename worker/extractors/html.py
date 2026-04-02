from __future__ import annotations

from shared.types import ExtractionError, ExtractionResult


def extract_html(html: str, url: str | None = None) -> ExtractionResult:
    """Extract article text from HTML using trafilatura."""
    import trafilatura

    result = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        output_format="txt",
    )

    if not result:
        raise ExtractionError("empty_content", "trafilatura returned no content")

    metadata: dict = {}
    meta = trafilatura.extract(
        html,
        url=url,
        output_format="xml",
        include_comments=False,
    )
    if meta:
        # Try to parse title/author from XML output
        import re
        title_match = re.search(r'title="([^"]*)"', meta)
        author_match = re.search(r'author="([^"]*)"', meta)
        if title_match:
            metadata["title"] = title_match.group(1)
        if author_match:
            metadata["author"] = author_match.group(1)

    if url:
        metadata["source_url"] = url
    metadata["word_count"] = len(result.split())

    return ExtractionResult(text=result, metadata=metadata)

from __future__ import annotations

import io

from shared.types import ExtractionError, ExtractionResult


def extract_pdf(data: bytes) -> ExtractionResult:
    """Extract text from PDF using pymupdf."""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text)

    doc.close()

    if not pages:
        # Try OCR fallback
        return _ocr_pdf(data)

    full_text = "\n\n".join(pages)
    return ExtractionResult(
        text=full_text,
        metadata={
            "page_count": len(pages),
            "word_count": len(full_text.split()),
            "mime_type": "application/pdf",
        },
    )


def _ocr_pdf(data: bytes) -> ExtractionResult:
    """OCR fallback for PDFs with no text layer."""
    import pymupdf
    from PIL import Image
    import pytesseract

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []

    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img)
        if text.strip():
            pages.append(text)

    doc.close()

    if not pages:
        raise ExtractionError("empty_content", "PDF has no extractable text even with OCR")

    full_text = "\n\n".join(pages)
    return ExtractionResult(
        text=full_text,
        metadata={
            "page_count": len(pages),
            "word_count": len(full_text.split()),
            "mime_type": "application/pdf",
            "extraction_method": "ocr",
        },
    )

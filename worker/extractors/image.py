from __future__ import annotations

import io

from shared.types import ExtractionError, ExtractionResult


def extract_image(data: bytes) -> ExtractionResult:
    """Extract text from image using pytesseract + Pillow."""
    from PIL import Image, ImageFilter
    import pytesseract

    img = Image.open(io.BytesIO(data))

    # Preprocessing for better OCR
    if img.mode != "L":
        img = img.convert("L")  # grayscale
    img = img.filter(ImageFilter.SHARPEN)

    text = pytesseract.image_to_string(img).strip()

    if not text:
        raise ExtractionError("empty_content", "OCR produced no text from image")

    return ExtractionResult(
        text=text,
        metadata={
            "word_count": len(text.split()),
            "image_size": f"{img.width}x{img.height}",
            "extraction_method": "ocr",
        },
    )

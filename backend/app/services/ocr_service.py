"""Independent text layer for a document.

Used to ground / cross-check what the LLM read (explainable confidence), NOT as the
primary extractor. Native PDFs use their embedded text; images and scanned PDFs use
Tesseract. If Tesseract is unavailable we degrade gracefully (no confidence scores).
"""
import io
from dataclasses import dataclass, field

import pypdfium2 as pdfium
from PIL import Image

from app.core.logging import get_logger
from app.services.document_validation_service import PDF

logger = get_logger(__name__)
MIN_NATIVE_TEXT_CHARS = 40


@dataclass
class OcrResult:
    pages: list[str] = field(default_factory=list)
    ocr_used: bool = False
    engine: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    @property
    def available(self) -> bool:
        return any(p.strip() for p in self.pages)


def _tesseract(image: Image.Image) -> str:
    import pytesseract

    # Two page-segmentation modes; the union catches boxed/shaded table columns that one mode misses.
    gray = image.convert("L")
    return "\n".join(pytesseract.image_to_string(gray, config=f"--psm {m}") for m in (6, 11))


def extract_text(content: bytes, file_type: str) -> OcrResult:
    """Never raises: OCR problems are logged and an empty result is returned."""
    try:
        if file_type == PDF:
            pdf = pdfium.PdfDocument(content)
            native = [pdf[i].get_textpage().get_text_bounded() for i in range(len(pdf))]
            if sum(len(t.strip()) for t in native) >= MIN_NATIVE_TEXT_CHARS:
                logger.info("Native PDF text layer used (%d pages)", len(native))
                return OcrResult(pages=native, ocr_used=False, engine="pdf-text-layer")
            images = [pdf[i].render(scale=3).to_pil() for i in range(len(pdf))]
        else:
            images = [Image.open(io.BytesIO(content))]
        pages = [_tesseract(img) for img in images]
        logger.info("Tesseract OCR completed (%d page(s))", len(pages))
        return OcrResult(pages=pages, ocr_used=True, engine="tesseract")
    except Exception as exc:  # noqa: BLE001 - OCR is best-effort
        logger.warning("OCR unavailable or failed: %s", exc)
        return OcrResult()

"""Independent text layer for a document.

Used to ground / cross-check what the LLM read (explainable confidence), NOT as the
primary extractor. Native PDFs use their embedded text; images and scanned PDFs use
Tesseract. If Tesseract is unavailable we degrade gracefully (no confidence scores).
"""
import io
from dataclasses import dataclass, field

import pypdfium2 as pdfium
from PIL import Image

from app.core.config import get_settings
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


def _prepare(image: Image.Image, max_pixels: int) -> Image.Image:
    """Greyscale + downscale to at most max_pixels so Tesseract stays within a small memory budget."""
    gray = image.convert("L")
    w, h = gray.size
    if w * h > max_pixels:
        ratio = (max_pixels / (w * h)) ** 0.5
        gray = gray.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
    return gray


def _tesseract(image: Image.Image) -> str:
    import pytesseract

    s = get_settings()
    gray = _prepare(image, s.ocr_max_pixels)
    # Two page-segmentation modes; the union catches boxed/shaded table columns that one mode misses.
    out = []
    for mode in (6, 11):
        try:
            out.append(pytesseract.image_to_string(gray, config=f"--psm {mode}", timeout=s.ocr_timeout_seconds))
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            logger.warning("Tesseract psm %d timed out: %s", mode, exc)
    return "\n".join(out)


def extract_text(content: bytes, file_type: str) -> OcrResult:
    """Never raises: OCR problems are logged and an empty result is returned."""
    if not get_settings().ocr_enabled:
        return OcrResult()
    try:
        if file_type == PDF:
            pdf = pdfium.PdfDocument(content)
            native = [pdf[i].get_textpage().get_text_bounded() for i in range(len(pdf))]
            if sum(len(t.strip()) for t in native) >= MIN_NATIVE_TEXT_CHARS:
                logger.info("Native PDF text layer used (%d pages)", len(native))
                return OcrResult(pages=native, ocr_used=False, engine="pdf-text-layer")
            pages = []
            for i in range(len(pdf)):  # one page at a time: never hold all rendered pages in memory
                img = pdf[i].render(scale=2).to_pil()
                pages.append(_tesseract(img))
                del img
        else:
            with Image.open(io.BytesIO(content)) as img:
                pages = [_tesseract(img)]
        logger.info("Tesseract OCR completed (%d page(s))", len(pages))
        return OcrResult(pages=pages, ocr_used=True, engine="tesseract")
    except Exception as exc:  # noqa: BLE001 - OCR is best-effort
        logger.warning("OCR unavailable or failed: %s", exc)
        return OcrResult()

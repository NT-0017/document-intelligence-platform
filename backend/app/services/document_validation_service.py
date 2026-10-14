"""Input-control layer: validates the uploaded file BEFORE any OCR / AI call.

Checks (in order): not empty, size limit, real type via magic bytes (not just the
extension), readable/uncorrupted, page count <= limit. It never classifies the
document's business type.
"""
import io

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.document import FileValidation

logger = get_logger(__name__)

PDF, JPG, PNG = "application/pdf", "image/jpeg", "image/png"

# error code -> HTTP status
ERROR_STATUS = {
    "EMPTY_FILE": 400,
    "FILE_TOO_LARGE": 413,
    "UNSUPPORTED_FILE_TYPE": 415,
    "CORRUPTED_FILE": 422,
    "PAGE_LIMIT_EXCEEDED": 422,
}


def detect_file_type(content: bytes) -> str | None:
    """Detect the real type from magic bytes; returns a MIME type or None."""
    head = content[:1024].lstrip()
    if head.startswith(b"%PDF-"):
        return PDF
    if content.startswith(b"\xff\xd8\xff"):
        return JPG
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    return None


def _fail(result: FileValidation, code: str, message: str) -> FileValidation:
    result.status = "FAIL"
    result.error_code = code
    result.error_message = message
    logger.warning("File validation failed: %s - %s", code, message)
    return result


def validate_file(file_name: str, content: bytes, settings: Settings | None = None) -> FileValidation:
    settings = settings or get_settings()
    result = FileValidation()

    if not content:
        return _fail(result, "EMPTY_FILE", "The uploaded file is empty.")
    if len(content) > settings.max_file_size_bytes:
        return _fail(result, "FILE_TOO_LARGE", f"File exceeds the {settings.max_file_size_mb} MB limit.")

    file_type = detect_file_type(content)
    if file_type is None:
        return _fail(result, "UNSUPPORTED_FILE_TYPE", "Only PDF / JPG / PNG documents are supported.")
    result.file_type = file_type
    result.is_supported = True

    try:
        if file_type == PDF:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                return _fail(result, "CORRUPTED_FILE", "The PDF is password-protected and cannot be read.")
            page_count = len(reader.pages)
            if page_count > 0:
                reader.pages[0].extract_text()  # force a real parse to catch corruption
        else:
            with Image.open(io.BytesIO(content)) as img:
                img.verify()
            page_count = 1
    except (PyPdfError, UnidentifiedImageError, OSError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("Unreadable file %s: %s", file_name, exc)
        return _fail(result, "CORRUPTED_FILE", "The file is corrupted or cannot be read.")

    result.is_readable = True
    result.page_count = page_count
    if page_count < 1:
        return _fail(result, "CORRUPTED_FILE", "The document has no pages.")
    if page_count > settings.max_pages:
        return _fail(
            result,
            "PAGE_LIMIT_EXCEEDED",
            f"Document has {page_count} pages; the maximum is {settings.max_pages}.",
        )

    result.status = "PASS"
    logger.info("File validation passed: %s (%s, %d page(s))", file_name, file_type, page_count)
    return result

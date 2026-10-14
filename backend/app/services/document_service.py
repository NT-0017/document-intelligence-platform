"""Orchestrates the pipeline: validate -> OCR -> extract -> financial checks -> confidence -> store."""
import os
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, ExtractionError, FileValidationError
from app.core.logging import get_logger
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentType
from app.services import document_validation_service as fvs
from app.services.extraction_service import ExtractionService
from app.services.financial_validation_service import run_validation
from app.services.ocr_service import extract_text
from app.utils.confidence import LOW_CONFIDENCE_THRESHOLD, apply_confidence

logger = get_logger(__name__)

# Minimum fields we expect; absent ones are reported in validation.missing_required_fields
REQUIRED = {
    DocumentType.INVOICE: ["invoice_number", "invoice_date", "vendor_name", "currency", "total_amount"],
    DocumentType.BALANCE_SHEET: ["total_assets", "total_capital_and_liabilities"],
    DocumentType.PROFIT_AND_LOSS: ["total_income", "total_expenditure", "profit_before_minority_interest",
                                   "net_profit_attributable_to_group"],
    DocumentType.CASH_FLOW_STATEMENT: ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
                                       "net_change_in_cash", "opening_cash", "closing_cash"],
}


def safe_name(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    return (base or "unnamed")[:255]


def _missing(document_type: DocumentType, data: dict) -> list[str]:
    missing = []
    for key in REQUIRED[document_type]:
        if document_type == DocumentType.INVOICE:
            if (data.get(key) or {}).get("value") is None:
                missing.append(key)
        else:
            figs = data.get("key_figures", {}).get(key, {})
            absent = [p for p in data.get("periods", []) if p not in figs]
            if not figs:
                missing.append(key)
            elif absent:
                missing.append(f"{key} ({', '.join(absent)})")
    return missing


def _low_confidence(data: dict) -> list[str]:
    low = [k for k, f in data.items() if isinstance(f, dict) and f.get("confidence") is not None
           and f["confidence"] < LOW_CONFIDENCE_THRESHOLD]
    low += [f"line_items[{i}]" for i, li in enumerate(data.get("line_items", []))
            if li.get("confidence") is not None and li["confidence"] < LOW_CONFIDENCE_THRESHOLD]
    return low


class DocumentService:
    def __init__(self, db: Session, extractor: ExtractionService):
        self.repo = DocumentRepository(db)
        self.extractor = extractor

    def _store(self, result: dict, started: float) -> dict:
        now = datetime.now(timezone.utc)
        ms = int((time.perf_counter() - started) * 1000)
        result["processing_metadata"].update(
            {"processed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "processing_time_ms": ms})
        self.repo.add(Document(
            document_name=result["document_name"], document_type=result["document_type"],
            processing_status=result["processing_status"],
            validation_status=(result.get("validation") or {}).get("overall_status"),
            overall_confidence=result.get("overall_confidence"), processing_time_ms=ms,
            result=result, processed_at=now.replace(tzinfo=None)))
        return result

    def _failed(self, name, doc_type, file_validation, code, message, started, meta=None) -> dict:
        result = {
            "document_name": name, "document_type": doc_type.value, "processing_status": "FAILED",
            "overall_confidence": None, "file_validation": file_validation, "extracted_data": None,
            "validation": None, "error": {"code": code, "message": message},
            "processing_metadata": {"ocr_used": False, **(meta or {})},
        }
        try:
            self._store(result, started)
        except AppError:  # never mask the original error with a storage failure
            logger.error("Could not store FAILED record for %s", name)
        return result

    def process(self, file_name: str | None, content: bytes, document_type: DocumentType) -> dict:
        started = time.perf_counter()
        name = safe_name(file_name)
        logger.info("Processing request: name=%s type=%s bytes=%d", name, document_type.value, len(content))

        fv = fvs.validate_file(name, content)
        if fv.status != "PASS":
            self._failed(name, document_type, fv.model_dump(exclude_none=True), fv.error_code,
                         fv.error_message, started)
            raise FileValidationError(fv.error_message, fv.error_code, fvs.ERROR_STATUS.get(fv.error_code, 422))

        ocr = extract_text(content, fv.file_type)
        try:
            data = self.extractor.extract(content, fv.file_type, document_type)
            model = self.extractor.model_name
        except ExtractionError as exc:
            self._failed(name, document_type, fv.model_dump(exclude_none=True), exc.code, exc.message, started,
                         {"ocr_used": ocr.ocr_used})
            raise
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected extraction failure for %s", name)
            self._failed(name, document_type, fv.model_dump(exclude_none=True), "INTERNAL_ERROR",
                         "An unexpected error occurred while processing the document.", started)
            raise AppError("An unexpected error occurred while processing the document.") from exc

        confidence = apply_confidence(data, ocr.text) if ocr.available else None
        validation = run_validation(document_type, data)
        validation["missing_required_fields"] = _missing(document_type, data)
        validation["low_confidence_fields"] = _low_confidence(data)
        status = "FAIL" if validation["overall_status"] == "FAIL" else "PASS"

        result = {
            "document_name": name, "document_type": document_type.value,
            "processing_status": "FAILED" if status == "FAIL" else "PASS",
            "overall_confidence": confidence,
            "file_validation": fv.model_dump(exclude={"error_code", "error_message"}),
            "extracted_data": data, "validation": validation,
            "processing_metadata": {"ocr_used": ocr.ocr_used, "ocr_engine": ocr.engine, "model": model},
        }
        logger.info("Processed %s: status=%s validation=%s confidence=%s", name, result["processing_status"],
                    validation["overall_status"], confidence)
        return self._store(result, started)

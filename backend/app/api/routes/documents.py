from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import DocumentNotFoundError, InvalidRequestError
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentType
from app.schemas.response import DocumentList, DocumentSummary, ErrorResponse
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionService

router = APIRouter(prefix="/api/v1", tags=["documents"])

_extractor = ExtractionService()


def get_extractor() -> ExtractionService:  # overridable in tests
    return _extractor


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


ERRORS = {400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse},
          422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}}


@router.post("/documents/process", responses=ERRORS, summary="Upload and process a document")
async def process_document(
    file: UploadFile = File(..., description="PDF / JPG / PNG, max 3 pages"),
    document_type: DocumentType = Form(..., description="invoice | balance_sheet | profit_and_loss | cash_flow_statement"),
    db: Session = Depends(get_db),
    extractor: ExtractionService = Depends(get_extractor),
):
    limit = get_settings().max_file_size_bytes
    content = await file.read(limit + 1)  # bounded read; oversize is rejected by validation
    if file.filename is None and not content:
        raise InvalidRequestError("A file is required.")
    return DocumentService(db, extractor).process(file.filename, content, document_type)


@router.get("/documents", response_model=DocumentList, summary="List processed documents")
def list_documents(
    q: str | None = Query(None, description="Search by document name"),
    document_type: DocumentType | None = None,
    status: str | None = Query(None, pattern="^(PASS|FAILED)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total, rows = DocumentRepository(db).list(q, document_type.value if document_type else None, status, limit, offset)
    return DocumentList(total=total, items=[
        DocumentSummary(id=r.id, document_name=r.document_name, document_type=r.document_type,
                        processing_status=r.processing_status, validation_status=r.validation_status,
                        overall_confidence=r.overall_confidence, processed_at=_iso(r.processed_at),
                        processing_time_ms=r.processing_time_ms) for r in rows])


@router.get("/documents/{document_name}", responses={404: {"model": ErrorResponse}},
            summary="Latest result for a document name")
def get_document(document_name: str, db: Session = Depends(get_db)):
    doc = DocumentRepository(db).get_latest_by_name(document_name)
    if doc is None:
        raise DocumentNotFoundError(f"No processed document named '{document_name}'.")
    return doc.result

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class DocumentSummary(BaseModel):
    id: int
    document_name: str
    document_type: str
    processing_status: str
    validation_status: str | None = None
    overall_confidence: float | None = None
    processed_at: str
    processing_time_ms: int | None = None


class DocumentList(BaseModel):
    total: int
    items: list[DocumentSummary]

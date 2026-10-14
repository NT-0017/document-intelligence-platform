"""API-level schemas for documents."""
from enum import Enum

from pydantic import BaseModel


class DocumentType(str, Enum):
    INVOICE = "invoice"
    BALANCE_SHEET = "balance_sheet"
    PROFIT_AND_LOSS = "profit_and_loss"
    CASH_FLOW_STATEMENT = "cash_flow_statement"


class FileValidation(BaseModel):
    file_type: str | None = None
    is_supported: bool = False
    is_readable: bool = False
    page_count: int | None = None
    status: str = "FAIL"  # PASS | FAIL
    error_code: str | None = None
    error_message: str | None = None

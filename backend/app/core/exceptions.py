"""Application errors. Each carries a stable error code and an HTTP status."""


class AppError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class InvalidRequestError(AppError):
    code = "INVALID_REQUEST"
    status_code = 400


class FileValidationError(AppError):
    status_code = 422


class ExtractionError(AppError):
    code = "EXTRACTION_FAILED"
    status_code = 502


class DocumentNotFoundError(AppError):
    code = "DOCUMENT_NOT_FOUND"
    status_code = 404


class DatabaseError(AppError):
    code = "DATABASE_ERROR"
    status_code = 500

"""All database access for documents lives here."""
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import DatabaseError
from app.core.logging import get_logger
from app.models.document import Document

logger = get_logger(__name__)


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, doc: Document) -> Document:
        try:
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)
            return doc
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.exception("DB write failed")
            raise DatabaseError("Could not store the processing result.") from exc

    def get_latest_by_name(self, name: str) -> Document | None:
        try:
            stmt = select(Document).where(Document.document_name == name).order_by(Document.id.desc()).limit(1)
            return self.db.execute(stmt).scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("DB read failed")
            raise DatabaseError("Could not read from the database.") from exc

    def list(self, q: str | None = None, document_type: str | None = None, status: str | None = None,
             limit: int = 50, offset: int = 0) -> tuple[int, list[Document]]:
        try:
            filters = []
            if q:
                filters.append(Document.document_name.ilike(f"%{q}%"))
            if document_type:
                filters.append(Document.document_type == document_type)
            if status:
                filters.append(Document.processing_status == status)
            total = self.db.execute(select(func.count(Document.id)).where(*filters)).scalar_one()
            rows = self.db.execute(
                select(Document).where(*filters).order_by(Document.id.desc()).limit(limit).offset(offset)
            ).scalars().all()
            return total, list(rows)
        except SQLAlchemyError as exc:
            logger.exception("DB list failed")
            raise DatabaseError("Could not read from the database.") from exc

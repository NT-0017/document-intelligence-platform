from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import engine

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", summary="Health check")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "unavailable"
    return {"status": "ok" if db == "ok" else "degraded", "database": db}

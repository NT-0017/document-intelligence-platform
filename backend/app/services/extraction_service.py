"""AI-based field & table extraction (LLM -> validated Pydantic model -> normalized dict)."""
import json
import re

from pydantic import ValidationError

from app.core.exceptions import ExtractionError
from app.core.logging import get_logger
from app.schemas.document import DocumentType
from app.services.llm_client import LLMClient
from app.utils.normalize import normalize_invoice, normalize_statement
from app.utils.prompts import SYSTEM, build_prompt, schema_model

logger = get_logger(__name__)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ExtractionService:
    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:  # created lazily so the app (and /health) start without an API key
            from app.services.llm_client import GeminiClient

            self._llm = GeminiClient()
        return self._llm

    @property
    def model_name(self) -> str:
        return self.llm.model_name

    def extract(self, content: bytes, mime_type: str, document_type: DocumentType) -> dict:
        model_cls = schema_model(document_type)
        prompt = build_prompt(document_type)
        last_error = ""
        for attempt in (1, 2):  # second attempt re-asks once with the validation error
            ask = prompt if attempt == 1 else f"{prompt}\n\nYour previous answer was invalid: {last_error}\nReturn corrected JSON."
            raw = self.llm.generate_json(SYSTEM, ask, content, mime_type)
            try:
                parsed = model_cls.model_validate_json(_FENCE.sub("", raw.strip()))
                break
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)[:500]
                logger.warning("Model output failed schema validation (attempt %d): %s", attempt, last_error)
        else:
            raise ExtractionError("The model returned data that could not be parsed.",
                                  "EXTRACTION_INVALID_OUTPUT", 502)

        data = normalize_invoice(parsed) if document_type == DocumentType.INVOICE else normalize_statement(parsed)
        logger.info("Extraction complete for %s", document_type.value)
        return data

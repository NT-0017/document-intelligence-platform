"""Thin LLM abstraction. Swap providers by implementing `generate_json`."""
import time
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.exceptions import ExtractionError
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMClient(Protocol):
    model_name: str

    def generate_json(self, system: str, prompt: str, content: bytes, mime_type: str) -> str: ...


class GeminiClient:
    MAX_ATTEMPTS = 3

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        if not settings.gemini_api_key:
            raise ExtractionError("The extraction model is not configured.", "LLM_NOT_CONFIGURED", 503)
        from google import genai
        from google.genai import types

        self._types = types
        self.model_name = settings.gemini_model
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
        )

    def generate_json(self, system: str, prompt: str, content: bytes, mime_type: str) -> str:
        from google.genai import errors

        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.0, response_mime_type="application/json"
        )
        parts = [types.Part.from_bytes(data=content, mime_type=mime_type), prompt]
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                logger.info("LLM call (model=%s, attempt=%d)", self.model_name, attempt)
                resp = self._client.models.generate_content(model=self.model_name, contents=parts, config=config)
                if not resp.text:
                    raise ExtractionError("The model returned an empty response.", "LLM_EMPTY_RESPONSE", 502)
                return resp.text
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                retryable = code in (429, 500, 502, 503, 504)
                logger.warning("LLM API error code=%s attempt=%d: %s", code, attempt, exc)
                if retryable and attempt < self.MAX_ATTEMPTS:
                    time.sleep(2 * attempt)
                    continue
                if code == 429:
                    raise ExtractionError("The extraction model is rate-limited; please retry shortly.",
                                          "LLM_RATE_LIMITED", 503) from exc
                raise ExtractionError("The extraction model request failed.", "LLM_REQUEST_FAILED", 502) from exc
            except ExtractionError:
                raise
            except Exception as exc:  # noqa: BLE001 - timeouts / network
                logger.error("LLM call failed: %s", exc)
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(2 * attempt)
                    continue
                raise ExtractionError("The extraction model timed out or is unreachable.",
                                      "LLM_TIMEOUT", 504) from exc
        raise ExtractionError("The extraction model request failed.", "LLM_REQUEST_FAILED", 502)

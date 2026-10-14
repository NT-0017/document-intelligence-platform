import json

import pytest

from app.core.exceptions import ExtractionError
from app.schemas.document import DocumentType
from app.schemas.extraction import StatementExtraction
from app.services.extraction_service import ExtractionService
from app.utils.confidence import apply_confidence, numbers_in
from app.utils.normalize import normalize_statement
from tests.fakes import FakeLLM, P22, P23, pl_json, receipt_json


def test_statement_normalization_builds_key_figures_per_period():
    data = normalize_statement(StatementExtraction.model_validate(pl_json()))
    assert data["key_figures"]["total_income"] == {P23: 204666.10, P22: 167695.40}
    row = next(r for r in data["line_items"] if r["canonical_key"] == "interest_earned")
    assert row["values"][P23] == 170754.05 and row["raw_values"][P22] == "135,936.41"


def test_missing_values_stay_null_not_invented():
    payload = pl_json()
    payload["line_items"][1]["values"][0]["value"] = None  # unreadable cell
    data = normalize_statement(StatementExtraction.model_validate(payload))
    assert data["line_items"][1]["values"][P23] is None
    assert P23 not in data["key_figures"]["other_income"]


def test_markdown_fenced_json_is_accepted():
    svc = ExtractionService(FakeLLM(raw="```json\n" + json.dumps(receipt_json()) + "\n```"))
    assert svc.extract(b"x", "image/png", DocumentType.INVOICE)["total_amount"]["value"] == 30.30


def test_extraction_gives_up_after_two_invalid_answers():
    llm = FakeLLM(raw="nope")
    with pytest.raises(ExtractionError):
        ExtractionService(llm).extract(b"x", "image/png", DocumentType.INVOICE)
    assert llm.calls == 2


def test_numbers_in_handles_brackets_commas_and_decimal_comma():
    assert {1234.5, 7.0, 1.72} <= numbers_in("Total 1,234.50 (7.00) GST 1,72")


def test_confidence_high_when_ocr_agrees_low_when_not():
    data = {"total_amount": {"value": 30.30}, "subtotal": {"value": 99.99}, "line_items": []}
    overall = apply_confidence(data, "TOTAL: 30.30")
    assert data["total_amount"]["confidence"] == 0.95
    assert data["subtotal"]["confidence"] == 0.60
    assert overall == pytest.approx(0.775, abs=0.006)  # mean of 0.95 and 0.60


def test_no_ocr_text_means_no_confidence():
    assert apply_confidence({"total_amount": {"value": 1.0}, "line_items": []}, "  ") is None

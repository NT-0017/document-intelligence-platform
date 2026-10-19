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


# ---- tolerance to messy model output (seen with small models) --------------------------------
def test_null_fields_bare_values_and_string_numbers_are_accepted():
    messy = {"invoice_number": "593101", "vendor_address": None, "customer_name": None,
             "total_amount": "RM 30.30", "tax_included_in_total": "true", "line_items": None,
             "other_fields": None, "currency": {"value": "RM"}}
    data = ExtractionService(FakeLLM(raw=json.dumps(messy))).extract(b"x", "image/png", DocumentType.INVOICE)
    assert data["invoice_number"]["value"] == "593101"
    assert data["vendor_address"]["value"] is None            # null -> missing, not a parse failure
    assert data["total_amount"]["value"] == 30.30
    assert data["tax_included_in_total"]["value"] is True
    assert data["line_items"] == []


def test_statement_with_dict_values_unknown_enums_and_bracket_strings():
    messy = {"periods": ["A", "B"], "line_items": [
        {"label": "Net cash", "row_type": "weird", "canonical_key": "invented_key",
         "values": {"A": "(1,234.50)", "B": "-"}},
        {"label": "Total", "row_type": "total", "canonical_key": "total_income",
         "values": [{"period": "A", "raw_text": "(500)"}]}]}
    data = ExtractionService(FakeLLM(raw=json.dumps(messy))).extract(b"x", "application/pdf",
                                                                     DocumentType.PROFIT_AND_LOSS)
    first, second = data["line_items"]
    assert first["canonical_key"] is None and first["row_type"] == "item"
    assert first["values"] == {"A": -1234.5, "B": None}
    assert second["values"]["A"] == -500.0 and data["key_figures"]["total_income"]["A"] == -500.0


def test_wrapped_and_list_wrapped_answers_are_unwrapped():
    inner = receipt_json()
    for wrapped in ([inner], {"invoice": inner}, {"extracted_data": inner}):
        data = ExtractionService(FakeLLM(raw=json.dumps(wrapped))).extract(b"x", "image/png", DocumentType.INVOICE)
        assert data["total_amount"]["value"] == 30.30


def test_attributable_profit_recovered_and_numeric_labels_renamed():
    from app.schemas.extraction import StatementExtraction
    from app.utils.normalize import normalize_statement

    def row(label, a, b, key=None, rt="item"):
        return {"label": label, "row_type": rt, "section": "other", "canonical_key": key,
                "values": [{"period": "FY21", "value": a}, {"period": "FY20", "value": b}]}

    ex = StatementExtraction.model_validate({
        "periods": ["FY21", "FY20"],
        "line_items": [
            row("Net profit for the year", 318567681, 272962653, "profit_before_minority_interest"),
            row("Less : Minority interest", 235590, 423147, "minority_interest"),
            row("Consolidated profit for the year", 318332091, 272539506, None),
            row("367,373,400", 1, 2),
        ]})
    out = normalize_statement(ex)
    assert out["key_figures"]["net_profit_attributable_to_group"]["FY21"] == 318332091
    assert out["line_items"][3]["label"] == "Subtotal" and out["line_items"][3]["row_type"] == "subtotal"
    # value-based fallback when the label is unhelpful
    ex.line_items[2].label = "Profit for the year after minorities"
    ex.line_items[2].canonical_key = None
    assert "net_profit_attributable_to_group" in normalize_statement(ex)["key_figures"]


def test_invoice_line_discount_parsed_and_empty_other_fields_dropped():
    from app.schemas.extraction import InvoiceExtraction
    from app.utils.normalize import normalize_invoice

    ex = InvoiceExtraction.model_validate({
        "line_items": [{"description": "x", "quantity": "6", "unit_price": "7.44", "amount": "0.45", "discount_percent": "99 %"}],
        "other_fields": [{"key": "delivery_note", "value": None}, {"key": "sales_man", "value": "SUJIT"}]})
    out = normalize_invoice(ex)
    assert out["line_items"][0]["discount_percent"] == 99.0
    assert [kv["key"] for kv in out["other_fields"]] == ["sales_man"]

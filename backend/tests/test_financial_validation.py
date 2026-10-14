import copy

from app.schemas.document import DocumentType
from app.services.financial_validation_service import run_validation

P23, P22 = "Year ended March 31, 2023", "Year ended March 31, 2022"


def pl_data():
    figs = {
        "interest_earned": (170754.05, 135936.41), "other_income": (33912.05, 31758.99),
        "total_income": (204666.10, 167695.40), "interest_expended": (77779.94, 58584.33),
        "operating_expenses": (51533.69, 40312.43), "provisions_and_contingencies": (29203.77, 30647.74),
        "total_expenditure": (158517.40, 129544.50), "profit_before_minority_interest": (46148.70, 38150.90),
        "minority_interest": (151.59, 98.15), "net_profit_attributable_to_group": (45997.11, 38052.75),
        "brought_forward_profit": (99062.77, 78594.20), "total_available_for_appropriation": (145059.88, 116646.95),
    }
    return {"periods": [P23, P22],
            "key_figures": {k: {P23: a, P22: b} for k, (a, b) in figs.items()}, "line_items": []}


def by_name(result, name, period=None):
    return [c for c in result["checks"] if c["name"] == name and (period is None or c.get("period") == period)]


def test_pl_all_pass_for_both_periods():
    r = run_validation(DocumentType.PROFIT_AND_LOSS, pl_data())
    assert r["overall_status"] == "PASS" and r["issues"] == []
    assert len(r["checks"]) == 10  # 5 checks x 2 periods
    assert all(c["status"] == "PASS" for c in r["checks"])


def test_pl_detects_wrong_value_only_in_affected_period():
    d = pl_data()
    d["key_figures"]["total_income"][P23] = 210000.00
    r = run_validation(DocumentType.PROFIT_AND_LOSS, d)
    assert r["overall_status"] == "FAIL"
    assert by_name(r, "total_income_check", P23)[0]["status"] == "FAIL"
    assert by_name(r, "total_income_check", P22)[0]["status"] == "PASS"
    assert r["issues"]


def test_missing_field_is_not_applicable_not_invented():
    d = pl_data()
    del d["key_figures"]["brought_forward_profit"]
    r = run_validation(DocumentType.PROFIT_AND_LOSS, d)
    c = by_name(r, "appropriation_check", P23)[0]
    assert c["status"] == "NOT_APPLICABLE" and c["calculated_value"] is None


def bs_data():
    items = [("assets", 60.0), ("assets", 40.0), ("capital_and_liabilities", 70.0), ("capital_and_liabilities", 30.0)]
    return {
        "periods": ["2023"],
        "key_figures": {"total_assets": {"2023": 100.0}, "total_capital_and_liabilities": {"2023": 100.0}},
        "line_items": [{"section": s, "row_type": "item", "values": {"2023": v}} for s, v in items],
    }


def test_balance_sheet_pass_and_component_sums():
    r = run_validation(DocumentType.BALANCE_SHEET, bs_data())
    assert r["overall_status"] == "PASS"
    assert len(r["checks"]) == 3


def test_balance_sheet_fail_when_unbalanced():
    d = bs_data()
    d["key_figures"]["total_assets"]["2023"] = 120.0
    r = run_validation(DocumentType.BALANCE_SHEET, d)
    assert by_name(r, "balance_sheet_equation_check")[0]["status"] == "FAIL"


def cf_data():
    kf = {"operating_cash_flow": 500.0, "investing_cash_flow": -300.0, "financing_cash_flow": -100.0,
          "net_change_in_cash": 100.0, "opening_cash": 50.0, "closing_cash": 150.0}
    return {"periods": ["FY23"], "key_figures": {k: {"FY23": v} for k, v in kf.items()}, "line_items": []}


def test_cash_flow_negatives_and_closing_balance():
    r = run_validation(DocumentType.CASH_FLOW_STATEMENT, cf_data())
    assert r["overall_status"] == "PASS"


def test_cash_flow_fx_adjustment_used_when_present():
    d = cf_data()
    d["key_figures"]["fx_adjustment"] = {"FY23": 5.0}
    d["key_figures"]["net_change_in_cash"]["FY23"] = 105.0
    d["key_figures"]["closing_cash"]["FY23"] = 155.0
    assert run_validation(DocumentType.CASH_FLOW_STATEMENT, d)["overall_status"] == "PASS"


def field(v):
    return {"value": v}


def invoice_data():
    return {
        "subtotal": field(28.58), "tax_amount": field(1.72), "discount": field(None), "rounding_adjustment": field(None),
        "total_amount": field(30.30), "tax_included_in_total": field(True), "cash_paid": field(50.0),
        "change_given": field(19.70),
        "line_items": [{"quantity": 1, "unit_price": 12.5, "amount": 12.5}, {"quantity": 1, "unit_price": 3.0, "amount": 3.0},
                       {"quantity": 1, "unit_price": 4.9, "amount": 4.9}, {"quantity": 1, "unit_price": 9.9, "amount": 9.9}],
    }


def test_invoice_receipt_passes():
    r = run_validation(DocumentType.INVOICE, invoice_data())
    assert r["overall_status"] == "PASS", r["issues"]
    names = [c["name"] for c in r["checks"]]
    assert "invoice_total_check" in names and "change_check" in names


def test_invoice_wrong_change_fails():
    d = invoice_data()
    d["change_given"] = field(10.0)
    r = run_validation(DocumentType.INVOICE, d)
    assert r["overall_status"] == "FAIL"


def test_invoice_without_cash_is_not_applicable():
    d = copy.deepcopy(invoice_data())
    d["cash_paid"] = field(None)
    c = [c for c in run_validation(DocumentType.INVOICE, d)["checks"] if c["name"] == "change_check"][0]
    assert c["status"] == "NOT_APPLICABLE"


def test_invoice_tax_separate_total_check():
    d = invoice_data()
    d["tax_included_in_total"] = field(False)
    d["total_amount"] = field(30.30)
    r = run_validation(DocumentType.INVOICE, d)
    assert [c for c in r["checks"] if c["name"] == "invoice_total_check"][0]["status"] == "PASS"

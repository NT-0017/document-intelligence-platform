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


# ---- real layouts that previously failed (HDFC statements in '000) ----------------------------
def test_cash_flow_with_amalgamation_line_inside_net_increase():
    # FY2017 column of the 2018 cash flow statement: net increase already includes the amalgamation cash.
    kf = {"operating_cash_flow": 172815931, "investing_cash_flow": -11476802, "financing_cash_flow": -58929743,
          "fx_adjustment": -282622, "cash_acquired_on_amalgamation": 295617, "net_change_in_cash": 102422381,
          "opening_cash": 390688815, "closing_cash": 493111196}
    d = {"periods": ["FY17"], "key_figures": {k: {"FY17": v} for k, v in kf.items()}, "line_items": []}
    r = run_validation(DocumentType.CASH_FLOW_STATEMENT, d)
    assert r["overall_status"] == "PASS", r["issues"]
    net = by_name(r, "net_change_in_cash_check")[0]
    assert "cash_acquired_on_amalgamation" in net["formula"] and net.get("note")  # transparent about the reading used
    closing = by_name(r, "closing_cash_check")[0]
    assert "cash_acquired_on_amalgamation" not in closing["formula"]  # not double counted


def test_cash_flow_wrong_numbers_still_fail():
    kf = {"operating_cash_flow": 100.0, "investing_cash_flow": -20.0, "financing_cash_flow": -10.0,
          "net_change_in_cash": 999.0, "opening_cash": 50.0, "closing_cash": 130.0}
    d = {"periods": ["FY"], "key_figures": {k: {"FY": v} for k, v in kf.items()}, "line_items": []}
    assert run_validation(DocumentType.CASH_FLOW_STATEMENT, d)["overall_status"] == "FAIL"


def test_pl_with_associates_and_amalgamation_rows():
    # FY2017 P&L: profit attributable includes associates; total available includes impact on amalgamation.
    kf = {"interest_earned": 732713529, "other_income": 128776329, "total_income": 861489858,
          "interest_expended": 380415844, "operating_expenses": 207510707, "provisions_and_contingencies": 120689285,
          "total_expenditure": 708615836, "profit_before_minority_interest": 152874022, "minority_interest": 367165,
          "share_in_profit_of_associates": 23393, "net_profit_attributable_to_group": 152530250,
          "impact_on_amalgamation": 274507, "brought_forward_profit": 248255886,
          "total_available_for_appropriation": 401060643}
    d = {"periods": ["FY17"], "key_figures": {k: {"FY17": v} for k, v in kf.items()}, "line_items": []}
    r = run_validation(DocumentType.PROFIT_AND_LOSS, d)
    assert r["overall_status"] == "PASS", r["issues"]
    assert all(c["status"] == "PASS" for c in r["checks"])


def test_pl_genuine_error_is_not_hidden_by_alternate_readings():
    d = pl_data()
    d["key_figures"]["total_available_for_appropriation"][P23] = 150000.00
    r = run_validation(DocumentType.PROFIT_AND_LOSS, d)
    assert by_name(r, "appropriation_check", P23)[0]["status"] == "FAIL"


def test_invoice_total_includes_shipping_and_flags_real_mismatch():
    # real batch2-0999: subtotal 804 + tax 63.47 + S&H 50 = 917.47, but the document prints 916.47
    def F(v): return {"value": v}
    data = {"subtotal": F(804.0), "tax_amount": F(63.47), "shipping_amount": F(50.0), "total_amount": F(916.47),
            "line_items": []}
    chk = [c for c in run_validation(DocumentType.INVOICE, data)["checks"] if c["name"] == "invoice_total_check"][0]
    assert chk["calculated_value"] == 917.47 and chk["status"] == "FAIL" and chk["variance"] == 1.0
    data["total_amount"] = F(917.47)
    assert [c for c in run_validation(DocumentType.INVOICE, data)["checks"] if c["name"] == "invoice_total_check"][0]["status"] == "PASS"


def test_invoice_line_discount_percent_is_honoured():
    # real GST invoice: 6 pcs x 7.44 with a 99 % line discount is printed as 0.45
    def F(v): return {"value": v}
    data = {"line_items": [
        {"quantity": 6, "unit_price": 7.44, "amount": 0.45, "discount_percent": 99},
        {"quantity": 8, "unit_price": 7.44, "amount": 0.6, "discount_percent": 99},
        {"quantity": 6, "unit_price": 7.44, "amount": 0.45}]}  # same line without a discount -> genuinely wrong
    checks = {c["name"]: c for c in run_validation(DocumentType.INVOICE, data)["checks"]}
    assert checks["line_item_1_check"]["status"] == "PASS" and checks["line_item_2_check"]["status"] == "PASS"
    assert checks["line_item_3_check"]["status"] == "FAIL"


def test_wrong_tax_included_flag_does_not_fail_a_consistent_gst_invoice():
    # real invoice SCI/25-26/3331: lines are pre-tax; "(Incl. of Tax)" is only a column heading
    def F(v): return {"value": v}
    lines = [2499.84, 0.45, 2064.60, 892.80, 0.60, 356.88]
    data = {"subtotal": F(5815.17), "tax_amount": F(1046.72), "rounding_adjustment": F(0.11),
            "total_amount": F(6862.0), "tax_included_in_total": F(True),
            "line_items": [{"amount": a} for a in lines]}
    chk = {c["name"]: c for c in run_validation(DocumentType.INVOICE, data)["checks"]}
    assert chk["line_items_sum_check"]["status"] == "PASS" and chk["invoice_total_check"]["status"] == "PASS"
    data["line_items"][0]["amount"] = 2000.0  # genuinely wrong lines still fail
    chk = {c["name"]: c for c in run_validation(DocumentType.INVOICE, data)["checks"]}
    assert chk["line_items_sum_check"]["status"] == "FAIL"


def test_unsigned_rounding_off_accepted_in_either_sign_but_real_errors_still_fail():
    def F(v): return {"value": v}
    base = {"subtotal": F(5815.17), "tax_amount": F(1046.72), "total_amount": F(6862.0), "line_items": []}
    for r in (0.11, -0.11):  # the model guessed the sign; the invoice prints plain 0.11
        chk = [c for c in run_validation(DocumentType.INVOICE, {**base, "rounding_adjustment": F(r)})["checks"]
               if c["name"] == "invoice_total_check"][0]
        assert chk["status"] == "PASS"
    chk = [c for c in run_validation(DocumentType.INVOICE, {**base, "total_amount": F(6870.0),
           "rounding_adjustment": F(-0.11)})["checks"] if c["name"] == "invoice_total_check"][0]
    assert chk["status"] == "FAIL"          # a real error is not masked

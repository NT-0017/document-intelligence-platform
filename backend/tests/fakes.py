"""A fake LLM that returns canned JSON, so tests never call a real model."""
import json


def F(value=None, src=None, page=1):
    return {"value": value, "source_text": src, "page_number": page if value is not None else None}


def receipt_json(total=30.30, change=19.70) -> dict:
    return {
        "invoice_number": F("593101", "INV No.: 593101"), "invoice_date": F("2018-02-14", "Date : 14-02-2018"),
        "vendor_name": F("SWEET FOREST CAFE", "SWEET FOREST CAFE"), "vendor_address": F(), "vendor_tax_id": F("000465809408"),
        "customer_name": F(), "currency": F("RM"), "subtotal": F(28.58, "Total (Excluding GST): 28.58"),
        "tax_amount": F(1.72, "GST payable (6%): 1.72"), "tax_rate_percent": F(6.0), "discount": F(),
        "rounding_adjustment": F(), "total_amount": F(total, "TOTAL: 30.30"),
        "tax_included_in_total": F(True, "Total (Inclusive of GST)"), "cash_paid": F(50.0, "CASH : 50.00"),
        "change_given": F(change, "CHANGE : 19.70"), "payment_method": F("CASH"),
        "line_items": [
            {"description": "Smoked Duck Spaghetti", "quantity": 1, "unit_price": 12.5, "amount": 12.5, "tax_code": "SR", "page_number": 1},
            {"description": "Hot Green Tea", "quantity": 1, "unit_price": 3.0, "amount": 3.0, "tax_code": "SR", "page_number": 1},
            {"description": "Coffee(H)", "quantity": 1, "unit_price": 4.9, "amount": 4.9, "tax_code": "SR", "page_number": 1},
            {"description": "Rendang Chicken Rice", "quantity": 1, "unit_price": 9.9, "amount": 9.9, "tax_code": "SR", "page_number": 1},
        ],
        "other_fields": [{"key": "table", "value": "15"}],
    }


P23, P22 = "Year ended March 31, 2023", "Year ended March 31, 2022"
_PL = [  # label, canonical_key, 2023, 2022
    ("Interest earned", "interest_earned", 170754.05, 135936.41),
    ("Other income", "other_income", 33912.05, 31758.99),
    ("Total", "total_income", 204666.10, 167695.40),
    ("Interest expended", "interest_expended", 77779.94, 58584.33),
    ("Operating expenses", "operating_expenses", 51533.69, 40312.43),
    ("Provisions and contingencies", "provisions_and_contingencies", 29203.77, 30647.74),
    ("Total", "total_expenditure", 158517.40, 129544.50),
    ("Consolidated Net Profit before minorities' interest", "profit_before_minority_interest", 46148.70, 38150.90),
    ("Less: Minorities' interest", "minority_interest", 151.59, 98.15),
    ("Consolidated Net Profit attributable to the group", "net_profit_attributable_to_group", 45997.11, 38052.75),
    ("Add: Brought forward profit", "brought_forward_profit", 99062.77, 78594.20),
    ("Total", "total_available_for_appropriation", 145059.88, 116646.95),
]


def pl_json(wrong_total_income_2023=None) -> dict:
    items = []
    for label, key, a, b in _PL:
        if key == "total_income" and wrong_total_income_2023:
            a = wrong_total_income_2023
        items.append({"label": label, "row_type": "total" if label == "Total" else "item", "section": "other",
                      "canonical_key": key, "values": [{"period": P23, "value": a, "raw_text": f"{a:,.2f}"},
                                                       {"period": P22, "value": b, "raw_text": f"{b:,.2f}"}],
                      "page_number": 1, "source_text": label})
    return {"entity_name": F("HDFC Bank Limited"), "statement_title": F("Consolidated Profit and Loss Account"),
            "currency": F("INR"), "unit": F("in crore"), "periods": [P23, P22], "line_items": items}


class FakeLLM:
    model_name = "fake-model"

    def __init__(self, payload=None, raw=None, error=None):
        self.payload, self.raw, self.error, self.calls = payload, raw, error, 0

    def generate_json(self, system, prompt, content, mime_type):
        self.calls += 1
        if self.error:
            raise self.error
        if self.raw is not None:
            return self.raw[min(self.calls, len(self.raw)) - 1] if isinstance(self.raw, list) else self.raw
        return json.dumps(self.payload)

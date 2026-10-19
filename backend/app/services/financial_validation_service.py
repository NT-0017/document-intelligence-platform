"""Deterministic financial checks. Never calls the LLM.

Each check returns: name, formula, operands, calculated_value, reported_value,
variance, status (PASS / FAIL / NOT_APPLICABLE) [+ period for statements].
A check whose inputs are missing is NOT_APPLICABLE - values are never assumed.
"""
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.document import DocumentType

logger = get_logger(__name__)

PASS, FAIL, NA = "PASS", "FAIL", "NOT_APPLICABLE"


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _check(name, formula, operands, calculated, reported, tol, period=None, note=None) -> dict:
    """Build a check dict; NOT_APPLICABLE if calculated/reported can't be determined."""
    out = {
        "name": name,
        "formula": formula,
        "operands": operands,
        "calculated_value": None,
        "reported_value": reported,
        "variance": None,
        "tolerance": tol,
        "status": NA,
    }
    if period is not None:
        out["period"] = period
    if note:
        out["note"] = note
    if calculated is None or reported is None:
        return out
    out["calculated_value"] = round(calculated, 4)
    out["variance"] = round(calculated - reported, 4)
    out["status"] = PASS if abs(calculated - reported) <= tol + 1e-9 else FAIL
    return out


def _fv(data: dict, key: str) -> float | None:
    f = data.get(key)
    return _num(f.get("value")) if isinstance(f, dict) else None


# ------------------------------- invoices ---------------------------------
def validate_invoice(data: dict, tol: float) -> list[dict]:
    checks: list[dict] = []
    items = data.get("line_items") or []

    for i, li in enumerate(items, start=1):
        q, p, a = _num(li.get("quantity")), _num(li.get("unit_price")), _num(li.get("amount"))
        disc = _num(li.get("discount_percent"))
        calc = q * p if q is not None and p is not None else None
        ops, formula = {"quantity": q, "unit_price": p}, "quantity * unit_price"
        if calc is not None and disc:
            calc *= 1 - disc / 100
            ops["discount_percent"] = disc
            formula = "quantity * unit_price * (1 - discount_percent / 100)"
        checks.append(_check(f"line_item_{i}_check", formula, ops, calc, a, tol))

    subtotal, tax, disc = _fv(data, "subtotal"), _fv(data, "tax_amount"), _fv(data, "discount")
    total, rounding = _fv(data, "total_amount"), _fv(data, "rounding_adjustment")
    ship = _fv(data, "shipping_amount") or 0.0
    incl = (data.get("tax_included_in_total") or {}).get("value")

    d, r = disc or 0.0, rounding or 0.0
    amounts = [_num(li.get("amount")) for li in items]
    if items and all(a is not None for a in amounts):
        total_amt = sum(amounts)
        if incl and total is not None:
            # line prices already include tax -> compare with the payable total
            checks.append(_check("line_items_sum_check",
                                 "sum(line_item.amount) - discount + rounding_adjustment (prices include tax)",
                                 {"line_amounts": amounts, "discount": d, "rounding_adjustment": r},
                                 total_amt - d + r, total, tol))
        elif subtotal is not None:
            checks.append(_check("line_items_sum_check", "sum(line_item.amount)",
                                 {"line_amounts": amounts}, total_amt, subtotal, tol))
        elif total is not None and tax in (None, 0):
            checks.append(_check("line_items_sum_check", "sum(line_item.amount) - discount + rounding_adjustment",
                                 {"line_amounts": amounts, "discount": d, "rounding_adjustment": r},
                                 total_amt - d + r, total, tol))
        else:
            checks.append(_check("line_items_sum_check", "sum(line_item.amount)", {"line_amounts": amounts},
                                 None, None, tol, note="Tax is shown separately and no subtotal was found."))
    else:
        checks.append(_check("line_items_sum_check", "sum(line_item.amount)", {}, None, subtotal, tol,
                             note="Line item amounts not fully available."))

    # Total check. 'subtotal' = amount before tax. If the document says tax is already
    # included and the subtotal-based formula does not reconcile, also try the tax-inclusive reading.
    if subtotal is not None and total is not None:
        if tax is not None:
            ops = {"subtotal": subtotal, "tax_amount": tax, "discount": d, "rounding_adjustment": r,
                   "shipping_amount": ship}
            res = _check("invoice_total_check", "subtotal + tax_amount + shipping_amount - discount + rounding_adjustment",
                         ops, subtotal + tax + ship - d + r, total, tol)
            if res["status"] == FAIL and incl:
                alt = _check("invoice_total_check",
                             "subtotal + shipping_amount - discount + rounding_adjustment (tax already included in subtotal)",
                             {"subtotal": subtotal, "shipping_amount": ship, "discount": d, "rounding_adjustment": r},
                             subtotal + ship - d + r, total, tol)
                if alt["status"] == PASS:
                    res = alt
            checks.append(res)
        else:
            checks.append(_check("invoice_total_check", "subtotal - discount + rounding_adjustment",
                                 {"subtotal": subtotal, "discount": d, "rounding_adjustment": r},
                                 subtotal - d + r, total, tol,
                                 note="No separate tax amount shown."))
    else:
        checks.append(_check("invoice_total_check", "subtotal + tax_amount - discount + rounding_adjustment",
                             {"subtotal": subtotal, "tax_amount": tax}, None, total, tol))

    cash, change = _fv(data, "cash_paid"), _fv(data, "change_given")
    calc = cash - total if cash is not None and total is not None else None
    checks.append(_check("change_check", "cash_paid - total_amount",
                         {"cash_paid": cash, "total_amount": total}, calc, change, tol))
    return checks


# ------------------------------ statements --------------------------------
def _figure(data: dict, key: str, period: str) -> float | None:
    return (data.get("key_figures", {}).get(key) or {}).get(period)


def _label(terms: list[tuple[str, int]]) -> str:
    out = ""
    for i, (k, sign) in enumerate(terms):
        out += (k if sign > 0 else f"- {k}") if i == 0 else (f" + {k}" if sign > 0 else f" - {k}")
    return out


def _linear(name, data, period, tol, target_key, required, spec_optional=(), alt_optional=()) -> dict:
    """Check  sum(sign*value) = target.

    `required` terms are always used. Optional terms are only used if the document shows them:
    the spec reading (`spec_optional`) is tried first; if it does not reconcile, other readings that
    real statements use (`alt_optional`, e.g. an item that is already inside the reported subtotal)
    are tried. The reading that reconciles is reported, otherwise the spec reading is reported as FAIL.
    """
    from itertools import combinations

    target = _figure(data, target_key, period)
    req_vals = {k: _figure(data, k, period) for k, _ in required}
    present = [(k, sg) for k, sg in list(spec_optional) + list(alt_optional) if _figure(data, k, period) is not None]
    primary_opts = [t for t in present if t in list(spec_optional)]
    options = [primary_opts]
    for r in range(len(present) + 1):
        for combo in combinations(present, r):
            if list(combo) != primary_opts:
                options.append(list(combo))

    def build(opts):
        terms = list(required) + opts
        ops = {k: _figure(data, k, period) for k, _ in terms}
        calc = None if any(v is None for v in ops.values()) else sum(sg * ops[k] for k, sg in terms)
        return _check(name, _label(terms), ops, calc, target, tol, period=period), terms

    primary, _ = build(options[0])
    if primary["status"] != FAIL:
        return primary
    for opts in options[1:]:
        res, _terms = build(opts)
        if res["status"] == PASS:
            res["note"] = "Matched using a different reading of this statement's layout (an extra line is included in the reported figure)."
            return res
    return primary


def _components_check(data, section, total_key, period, tol) -> dict:
    vals = []
    for li in data.get("line_items", []):
        if li.get("section") == section and li.get("row_type") == "item":
            v = (li.get("values") or {}).get(period)
            if v is not None:
                vals.append(v)
    total = _figure(data, total_key, period)
    calc = sum(vals) if vals else None
    return _check(f"{section}_components_check", f"sum({section} line items) = {total_key}",
                  {"component_count": len(vals)}, calc, total, tol, period=period)


def validate_balance_sheet(data: dict, tol: float) -> list[dict]:
    checks = []
    for p in data.get("periods", []):
        ta = _figure(data, "total_assets", p)
        tcl = _figure(data, "total_capital_and_liabilities", p)
        if tcl is None:
            tl, te = _figure(data, "total_liabilities", p), _figure(data, "total_equity", p)
            if tl is not None and te is not None:
                tcl = tl + te
        checks.append(_check("balance_sheet_equation_check", "total_assets = total_capital_and_liabilities",
                             {"total_assets": ta, "total_capital_and_liabilities": tcl}, ta, tcl, tol, period=p))
        checks.append(_components_check(data, "capital_and_liabilities", "total_capital_and_liabilities", p, tol))
        checks.append(_components_check(data, "assets", "total_assets", p, tol))
    return checks


def validate_profit_and_loss(data: dict, tol: float) -> list[dict]:
    checks = []
    for p in data.get("periods", []):
        L = lambda name, target, req, **kw: _linear(name, data, p, tol, target, req, **kw)  # noqa: E731
        checks += [
            L("total_income_check", "total_income", [("interest_earned", 1), ("other_income", 1)]),
            L("total_expenditure_check", "total_expenditure",
              [("interest_expended", 1), ("operating_expenses", 1), ("provisions_and_contingencies", 1)]),
            L("profit_before_minority_interest_check", "profit_before_minority_interest",
              [("total_income", 1), ("total_expenditure", -1)]),
            L("net_profit_attributable_check", "net_profit_attributable_to_group",
              [("profit_before_minority_interest", 1), ("minority_interest", -1)],
              alt_optional=[("share_in_profit_of_associates", 1)]),
            L("appropriation_check", "total_available_for_appropriation",
              [("net_profit_attributable_to_group", 1), ("brought_forward_profit", 1)],
              alt_optional=[("impact_on_amalgamation", 1)]),
        ]
        if _figure(data, "revenue", p) is not None and _figure(data, "cost_of_sales", p) is not None:
            checks.append(L("gross_profit_check", "gross_profit", [("revenue", 1), ("cost_of_sales", -1)]))
    return checks


def validate_cash_flow(data: dict, tol: float) -> list[dict]:
    checks = []
    for p in data.get("periods", []):
        checks.append(_linear(
            "net_change_in_cash_check", data, p, tol, "net_change_in_cash",
            [("operating_cash_flow", 1), ("investing_cash_flow", 1), ("financing_cash_flow", 1)],
            spec_optional=[("fx_adjustment", 1)], alt_optional=[("cash_acquired_on_amalgamation", 1)]))
        checks.append(_linear(
            "closing_cash_check", data, p, tol, "closing_cash",
            [("opening_cash", 1), ("net_change_in_cash", 1)],
            spec_optional=[("cash_acquired_on_amalgamation", 1)]))
    return checks


def run_validation(document_type: DocumentType, data: dict, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    if document_type == DocumentType.INVOICE:
        checks = validate_invoice(data, settings.tolerance_invoice)
    else:
        fn = {
            DocumentType.BALANCE_SHEET: validate_balance_sheet,
            DocumentType.PROFIT_AND_LOSS: validate_profit_and_loss,
            DocumentType.CASH_FLOW_STATEMENT: validate_cash_flow,
        }[document_type]
        checks = fn(data, settings.tolerance_statement)

    statuses = {c["status"] for c in checks}
    overall = FAIL if FAIL in statuses else PASS if PASS in statuses else NA
    issues = [
        f"{c['name']}{' [' + c['period'] + ']' if c.get('period') else ''}: calculated "
        f"{c['calculated_value']} vs reported {c['reported_value']} (variance {c['variance']})"
        for c in checks if c["status"] == FAIL
    ]
    logger.info("Financial validation: %s (%d checks, %d failed)", overall, len(checks), len(issues))
    return {"checks": checks, "overall_status": overall, "issues": issues}

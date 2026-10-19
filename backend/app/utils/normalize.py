"""Turn the LLM's typed output into the stable JSON shape returned by the API."""
import re

from app.schemas.extraction import InvoiceExtraction, StatementExtraction

_NUMERIC_LABEL = re.compile(r"^[\d,.\s()\-\u2013]+$")
_ATTRIBUTABLE_LABEL = re.compile(
    r"(consolidated\s+(net\s+)?profit\s+for\s+the\s+(year|period)|profit\s+attributable|"
    r"net\s+profit\s+attributable|profit\s+after\s+minorit)", re.I)

_SCALARS = (
    "invoice_number", "invoice_date", "vendor_name", "vendor_address", "vendor_tax_id", "customer_name", "customer_address",
    "currency", "subtotal", "tax_amount", "tax_rate_percent", "discount", "shipping_amount", "rounding_adjustment",
    "total_amount", "tax_included_in_total", "cash_paid", "change_given", "payment_method",
)


def _field(f) -> dict:
    return {"value": f.value, "page_number": f.page_number, "source_text": f.source_text}


def normalize_invoice(ex: InvoiceExtraction) -> dict:
    out = {name: _field(getattr(ex, name)) for name in _SCALARS}
    out["line_items"] = [li.model_dump() for li in ex.line_items]
    out["other_fields"] = [kv.model_dump() for kv in ex.other_fields if (kv.value or "").strip()]
    return out


def normalize_statement(ex: StatementExtraction) -> dict:
    out = {name: _field(getattr(ex, name)) for name in ("entity_name", "statement_title", "currency", "unit")}
    out["periods"] = list(ex.periods)
    items, key_figures = [], {}
    for li in ex.line_items:
        values = {v.period: v.value for v in li.values}
        key = li.canonical_key.value if li.canonical_key else None
        items.append({
            "label": li.label,
            "row_type": li.row_type.value,
            "section": li.section.value,
            "canonical_key": key,
            "schedule_ref": li.schedule_ref,
            "values": values,
            "raw_values": {v.period: v.raw_text for v in li.values},
            "page_number": li.page_number,
            "source_text": li.source_text,
        })
        if key:
            slot = key_figures.setdefault(key, {})
            for period, val in values.items():
                if val is not None and period not in slot:  # first occurrence wins
                    slot[period] = val
    for it in items:  # unlabelled subtotal rows come back with the number as the label
        if it["label"] and _NUMERIC_LABEL.match(it["label"].strip()):
            it["label"] = "Subtotal"
            if it["row_type"] == "item":
                it["row_type"] = "subtotal"
    _fill_attributable_profit(items, key_figures, out["periods"])
    out["line_items"] = items
    out["key_figures"] = key_figures
    out["other_fields"] = [kv.model_dump() for kv in ex.other_fields if (kv.value or "").strip()]
    return out


def _fill_attributable_profit(items: list[dict], key_figures: dict, periods: list[str]) -> None:
    """If the model did not tag the profit-after-minority row, find it deterministically:
    first by its printed label, then by value (profit before minority interest - minority interest)."""
    key = "net_profit_attributable_to_group"
    pbm, mi = key_figures.get("profit_before_minority_interest"), key_figures.get("minority_interest")
    if key in key_figures or not periods or not pbm or mi is None:
        return
    free = [it for it in items if it["canonical_key"] in (None, "net_profit") and it["row_type"] != "heading"]
    chosen = next((it for it in free if _ATTRIBUTABLE_LABEL.search(it["label"] or "")), None)
    if chosen is None:
        def matches(it):
            for p in periods:
                v, a, b = it["values"].get(p), pbm.get(p), mi.get(p)
                if v is None or a is None or b is None or abs(v - (a - b)) > 1.0:
                    return False
            return True
        chosen = next((it for it in free if matches(it)), None)
    if chosen is not None:
        chosen["canonical_key"] = key
        key_figures[key] = {p: v for p, v in chosen["values"].items() if v is not None}

"""Turn the LLM's typed output into the stable JSON shape returned by the API."""
from app.schemas.extraction import InvoiceExtraction, StatementExtraction

_SCALARS = (
    "invoice_number", "invoice_date", "vendor_name", "vendor_address", "vendor_tax_id", "customer_name",
    "currency", "subtotal", "tax_amount", "tax_rate_percent", "discount", "rounding_adjustment",
    "total_amount", "tax_included_in_total", "cash_paid", "change_given", "payment_method",
)


def _field(f) -> dict:
    return {"value": f.value, "page_number": f.page_number, "source_text": f.source_text}


def normalize_invoice(ex: InvoiceExtraction) -> dict:
    out = {name: _field(getattr(ex, name)) for name in _SCALARS}
    out["line_items"] = [li.model_dump() for li in ex.line_items]
    out["other_fields"] = [kv.model_dump() for kv in ex.other_fields]
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
    out["line_items"] = items
    out["key_figures"] = key_figures
    out["other_fields"] = [kv.model_dump() for kv in ex.other_fields]
    return out

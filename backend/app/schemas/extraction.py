"""Schemas for the LLM's structured output (what Gemini must return).

Kept deliberately flat: every scalar carries its own evidence (source_text + page_number),
and missing values are null. Statement values are a list of {period, value} because
JSON-schema-constrained models cannot return dicts with arbitrary keys.
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.numbers import to_int, to_number


def _as_field(v):
    """LLMs often return null or a bare value where {value, source_text, page_number} is expected."""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    return {"value": v}


def _list_or_empty(v):
    return [] if v is None else v


class _Evidence(BaseModel):
    """Shared tolerance: null / bare-scalar inputs and string page numbers."""

    @model_validator(mode="before")
    @classmethod
    def _wrap(cls, v):
        return _as_field(v)

    @field_validator("page_number", mode="before", check_fields=False)
    @classmethod
    def _page(cls, v):
        return to_int(v)

    @field_validator("source_text", mode="before", check_fields=False)
    @classmethod
    def _src(cls, v):
        return None if v is None else str(v)


class TextField(_Evidence):
    value: str | None = Field(None, description="Exactly as printed; null if not present in the document")
    source_text: str | None = Field(None, description="Short verbatim snippet the value was read from")
    page_number: int | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _text(cls, v):
        return None if v is None else str(v)


class NumberField(_Evidence):
    value: float | None = Field(None, description="Plain number, no currency symbol; null if not present")
    source_text: str | None = None
    page_number: int | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _num(cls, v):
        return to_number(v)


class BoolField(_Evidence):
    value: bool | None = None
    source_text: str | None = None
    page_number: int | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _bool(cls, v):
        if isinstance(v, str):
            return {"true": True, "yes": True, "false": False, "no": False}.get(v.strip().lower())
        return v


class KeyValue(_Evidence):
    key: str = Field("unknown", description="snake_case name of any other meaningful visible field")
    value: str | None = None
    source_text: str | None = None
    page_number: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _wrap(cls, v):  # a bare value has no key, so keep the default key
        return {} if v is None else v if isinstance(v, dict) else {"value": v}

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, v):
        return "unknown" if v is None else str(v)

    @field_validator("value", mode="before")
    @classmethod
    def _val(cls, v):
        return None if v is None else str(v)


class InvoiceLineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = Field(None, description="Line total as printed")
    discount_percent: float | None = Field(None, description="Per-line 'Disc %' column, e.g. 99 for '99 %'")
    tax_code: str | None = None
    page_number: int | None = None

    @field_validator("quantity", "unit_price", "amount", "discount_percent", mode="before")
    @classmethod
    def _nums(cls, v):
        return to_number(v)

    @field_validator("description", "tax_code", mode="before")
    @classmethod
    def _strs(cls, v):
        return None if v is None else str(v)

    @field_validator("page_number", mode="before")
    @classmethod
    def _pg(cls, v):
        return to_int(v)


class InvoiceExtraction(BaseModel):
    invoice_number: TextField = Field(default_factory=TextField)
    invoice_date: TextField = Field(default_factory=TextField, description="ISO YYYY-MM-DD if unambiguous, else as printed")
    vendor_name: TextField = Field(default_factory=TextField)
    vendor_address: TextField = Field(default_factory=TextField)
    vendor_tax_id: TextField = Field(default_factory=TextField)
    customer_name: TextField = Field(default_factory=TextField)
    customer_address: TextField = Field(default_factory=TextField, description="Bill-to / ship-to / job-site address")
    currency: TextField = Field(default_factory=TextField, description="ISO code or symbol as printed (e.g. RM, USD, INR)")
    subtotal: NumberField = Field(default_factory=NumberField, description="Amount before tax (e.g. 'Total excluding GST')")
    tax_amount: NumberField = Field(default_factory=NumberField)
    tax_rate_percent: NumberField = Field(default_factory=NumberField)
    discount: NumberField = Field(default_factory=NumberField)
    shipping_amount: NumberField = Field(default_factory=NumberField, description="Shipping / handling / freight / other charge added on top of the subtotal (e.g. S&H)")
    rounding_adjustment: NumberField = Field(default_factory=NumberField)
    total_amount: NumberField = Field(default_factory=NumberField, description="Final payable total")
    tax_included_in_total: BoolField = Field(
        default_factory=BoolField,
        description="True if the document says the total already includes GST/tax"
    )
    cash_paid: NumberField = Field(default_factory=NumberField)
    change_given: NumberField = Field(default_factory=NumberField)
    payment_method: TextField = Field(default_factory=TextField)
    line_items: list[InvoiceLineItem] = []
    other_fields: list[KeyValue] = []

    @field_validator("line_items", "other_fields", mode="before")
    @classmethod
    def _lists(cls, v):
        return _list_or_empty(v)


class RowType(str, Enum):
    ITEM = "item"          # a leaf line (not a sum of other lines)
    SUBTOTAL = "subtotal"  # sum of some lines within a section
    TOTAL = "total"        # the section / statement total
    HEADING = "heading"    # section title with no values


class CanonicalKey(str, Enum):
    # balance sheet
    TOTAL_ASSETS = "total_assets"
    TOTAL_CAPITAL_AND_LIABILITIES = "total_capital_and_liabilities"
    TOTAL_LIABILITIES = "total_liabilities"
    TOTAL_EQUITY = "total_equity"
    # profit & loss
    REVENUE = "revenue"
    COST_OF_SALES = "cost_of_sales"
    GROSS_PROFIT = "gross_profit"
    INTEREST_EARNED = "interest_earned"
    OTHER_INCOME = "other_income"
    TOTAL_INCOME = "total_income"
    INTEREST_EXPENDED = "interest_expended"
    OPERATING_EXPENSES = "operating_expenses"
    PROVISIONS_AND_CONTINGENCIES = "provisions_and_contingencies"
    TOTAL_EXPENDITURE = "total_expenditure"
    OPERATING_PROFIT = "operating_profit"
    TAX = "tax"
    PROFIT_BEFORE_MINORITY_INTEREST = "profit_before_minority_interest"
    MINORITY_INTEREST = "minority_interest"
    NET_PROFIT_ATTRIBUTABLE_TO_GROUP = "net_profit_attributable_to_group"
    NET_PROFIT = "net_profit"
    SHARE_IN_PROFIT_OF_ASSOCIATES = "share_in_profit_of_associates"
    IMPACT_ON_AMALGAMATION = "impact_on_amalgamation"
    BROUGHT_FORWARD_PROFIT = "brought_forward_profit"
    TOTAL_AVAILABLE_FOR_APPROPRIATION = "total_available_for_appropriation"
    # cash flow
    OPERATING_CASH_FLOW = "operating_cash_flow"
    INVESTING_CASH_FLOW = "investing_cash_flow"
    FINANCING_CASH_FLOW = "financing_cash_flow"
    FX_ADJUSTMENT = "fx_adjustment"
    NET_CHANGE_IN_CASH = "net_change_in_cash"
    OPENING_CASH = "opening_cash"
    CASH_ACQUIRED_ON_AMALGAMATION = "cash_acquired_on_amalgamation"
    CLOSING_CASH = "closing_cash"


class Section(str, Enum):
    ASSETS = "assets"
    CAPITAL_AND_LIABILITIES = "capital_and_liabilities"
    OTHER = "other"


class PeriodValue(BaseModel):
    period: str = Field("", description="Exactly one of the statement's period labels")
    value: float | None = Field(None, description="Brackets/parentheses => negative; null if blank or '-'")
    raw_text: str | None = Field(None, description="The cell exactly as printed")

    @field_validator("period", mode="before")
    @classmethod
    def _period(cls, v):
        return "" if v is None else str(v)

    @field_validator("raw_text", mode="before")
    @classmethod
    def _raw(cls, v):
        return None if v is None else str(v)

    @model_validator(mode="before")
    @classmethod
    def _fill_value_from_raw(cls, v):
        # Only when the model gave the printed cell but NO value key at all: parse what is printed
        # (brackets => negative). An explicit null is respected (the model judged it unreadable).
        if isinstance(v, dict) and "value" not in v and v.get("raw_text"):
            return {**v, "value": to_number(v["raw_text"])}
        return v

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, v):
        return to_number(v)


class StatementLineItem(BaseModel):
    label: str
    row_type: RowType
    section: Section = Section.OTHER
    canonical_key: CanonicalKey | None = Field(
        None, description="Only when the row clearly IS that figure; otherwise null. Never guess."
    )
    schedule_ref: str | None = Field(None, description="Schedule/note number column, if any")
    values: list[PeriodValue] = []
    page_number: int | None = None
    source_text: str | None = Field(None, description="Row text as printed")

    @field_validator("row_type", mode="before")
    @classmethod
    def _row_type(cls, v):
        v = str(v or "item").strip().lower()
        return v if v in {e.value for e in RowType} else "item"

    @field_validator("section", mode="before")
    @classmethod
    def _section(cls, v):
        v = str(v or "other").strip().lower()
        return v if v in {e.value for e in Section} else "other"

    @field_validator("canonical_key", mode="before")
    @classmethod
    def _key(cls, v):
        # An unknown / invented key must not fail the whole document: treat as untagged.
        v = None if v is None else str(v).strip().lower()
        return v if v in {e.value for e in CanonicalKey} else None

    @field_validator("values", mode="before")
    @classmethod
    def _values(cls, v):
        if v is None:
            return []
        if isinstance(v, dict):  # {"FY23": 1.0} instead of [{"period":..., "value":...}]
            return [{"period": k, "value": x} for k, x in v.items()]
        return v

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v):
        return "" if v is None else str(v)

    @field_validator("page_number", mode="before")
    @classmethod
    def _pg(cls, v):
        return to_int(v)

    @field_validator("schedule_ref", "source_text", mode="before")
    @classmethod
    def _strs(cls, v):
        return None if v is None else str(v)


class StatementExtraction(BaseModel):
    entity_name: TextField = Field(default_factory=TextField)
    statement_title: TextField = Field(default_factory=TextField)
    currency: TextField = Field(default_factory=TextField)
    unit: TextField = Field(default_factory=TextField, description="e.g. 'in crore', 'in millions', 'in thousands'")
    periods: list[str] = Field([], description="Period/column labels in left-to-right order")
    line_items: list[StatementLineItem] = []
    other_fields: list[KeyValue] = Field([], description="Notes, signatories, place, date etc.")

    @field_validator("periods", mode="before")
    @classmethod
    def _periods(cls, v):
        return [] if v is None else [str(x) for x in v] if isinstance(v, list) else [str(v)]

    @field_validator("line_items", "other_fields", mode="before")
    @classmethod
    def _lists(cls, v):
        return _list_or_empty(v)

"""Schemas for the LLM's structured output (what Gemini must return).

Kept deliberately flat: every scalar carries its own evidence (source_text + page_number),
and missing values are null. Statement values are a list of {period, value} because
JSON-schema-constrained models cannot return dicts with arbitrary keys.
"""
from enum import Enum

from pydantic import BaseModel, Field


class TextField(BaseModel):
    value: str | None = Field(None, description="Exactly as printed; null if not present in the document")
    source_text: str | None = Field(None, description="Short verbatim snippet the value was read from")
    page_number: int | None = None


class NumberField(BaseModel):
    value: float | None = Field(None, description="Plain number, no currency symbol; null if not present")
    source_text: str | None = None
    page_number: int | None = None


class BoolField(BaseModel):
    value: bool | None = None
    source_text: str | None = None
    page_number: int | None = None


class KeyValue(BaseModel):
    key: str = Field(description="snake_case name of any other meaningful visible field")
    value: str | None = None
    source_text: str | None = None
    page_number: int | None = None


class InvoiceLineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = Field(None, description="Line total as printed")
    tax_code: str | None = None
    page_number: int | None = None


class InvoiceExtraction(BaseModel):
    invoice_number: TextField = Field(default_factory=TextField)
    invoice_date: TextField = Field(default_factory=TextField, description="ISO YYYY-MM-DD if unambiguous, else as printed")
    vendor_name: TextField = Field(default_factory=TextField)
    vendor_address: TextField = Field(default_factory=TextField)
    vendor_tax_id: TextField = Field(default_factory=TextField)
    customer_name: TextField = Field(default_factory=TextField)
    currency: TextField = Field(default_factory=TextField, description="ISO code or symbol as printed (e.g. RM, USD, INR)")
    subtotal: NumberField = Field(default_factory=NumberField, description="Amount before tax (e.g. 'Total excluding GST')")
    tax_amount: NumberField = Field(default_factory=NumberField)
    tax_rate_percent: NumberField = Field(default_factory=NumberField)
    discount: NumberField = Field(default_factory=NumberField)
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
    period: str = Field(description="Exactly one of the statement's period labels")
    value: float | None = Field(None, description="Brackets/parentheses => negative; null if blank or '-'")
    raw_text: str | None = Field(None, description="The cell exactly as printed")


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


class StatementExtraction(BaseModel):
    entity_name: TextField = Field(default_factory=TextField)
    statement_title: TextField = Field(default_factory=TextField)
    currency: TextField = Field(default_factory=TextField)
    unit: TextField = Field(default_factory=TextField, description="e.g. 'in crore', 'in millions', 'in thousands'")
    periods: list[str] = Field([], description="Period/column labels in left-to-right order")
    line_items: list[StatementLineItem] = []
    other_fields: list[KeyValue] = Field([], description="Notes, signatories, place, date etc.")

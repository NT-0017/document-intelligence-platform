"""Prompts for the extraction model. Per-type hints keep canonical-key tagging accurate."""
import json

from app.schemas.document import DocumentType
from app.schemas.extraction import InvoiceExtraction, StatementExtraction

SYSTEM = """You are a meticulous financial document data-extraction engine.
Rules:
- Extract ONLY what is visible in the document. Never infer, calculate, correct or invent values.
  If a value is not present or unreadable, return null.
- Copy numbers exactly as printed (do not convert units or currencies). Copy identifiers (tax IDs, invoice
  numbers, account numbers) character by character; never drop or add a digit. Remove thousands separators
  and currency symbols. Brackets/parentheses mean a NEGATIVE number.
- For every value give source_text (a short verbatim snippet) and the 1-based page_number.
- Return a single JSON object that conforms to the provided JSON schema. No prose, no markdown."""

INVOICE_HINTS = """Document type: INVOICE / RECEIPT.
- invoice_number: the printed invoice/receipt/bill number. Handwritten annotations are NOT the invoice number;
  record them in other_fields (e.g. key 'handwritten_note').
- invoice_date: ISO YYYY-MM-DD whenever unambiguous (a month name such as 'Jan 06 2022' IS unambiguous -> 2022-01-06);
  only if day/month order is unclear keep it as printed. The printed text goes in source_text.
- subtotal = the amount BEFORE tax if the document prints one (e.g. 'Total (Excluding GST)'), otherwise null.
- tax_amount = tax actually printed (GST/VAT/SST). tax_included_in_total = true only if the document says the
  prices/total include tax. discount = null if none is printed.
- customer_address = ONLY an address printed under a Bill To / Ship To / Sold To / Customer / Client label (or a
  job-site address labelled as such). An address under 'From' or in the header is the vendor's, never the customer's.
  vendor_address = street/city/postcode only; put e-mail addresses and phone numbers in other_fields.
- shipping_amount = shipping / handling / freight / 'S&H' charge printed between the subtotal and the total.
- Do not put an address, postcode or code in other_fields 'reference' or 'notes' unless the document labels it that
  way; use the label printed next to it as the key (e.g. 'job_site', 'account_code').
- total_amount = the final payable total. cash_paid / change_given only if printed.
- line_items: every purchased row with description, quantity, unit_price, amount (line total as printed).
- Put every other meaningful visible field (cashier, table, GST registration number, GST summary, etc.) in other_fields."""

STATEMENT_COMMON = """Extract this financial statement completely.
- periods: the column/period labels exactly as printed, left to right (e.g. 'Year ended March 31, 2023').
- line_items: EVERY row in reading order, including headings (row_type 'heading', no values), items,
  subtotals and totals. row_type 'item' = a leaf row; 'subtotal'/'total' = a sum of other rows.
- values: one entry per period using exactly the period labels above. Blank or '-' => value null, keep raw_text.
- schedule_ref: the Schedule/Note number column if present.
- canonical_key: set ONLY when the row clearly is that figure, otherwise null (never guess).
- KEEP THE ANSWER SHORT: leave source_text null for line items (the label is the evidence); set raw_text ONLY when a
  cell is blank, '-' or unreadable; do not repeat the label anywhere else.
- entity_name/statement_title/currency/unit from the header (unit e.g. 'in crore'). Notes, signatories, place, date
  go in other_fields."""

HINTS = {
    DocumentType.BALANCE_SHEET: STATEMENT_COMMON + """
Balance sheet specifics:
- section: 'capital_and_liabilities' for rows from the Capital and Liabilities side, 'assets' for the Assets side.
- canonical_key: total of the assets side -> total_assets; total of capital & liabilities side ->
  total_capital_and_liabilities; explicit 'total liabilities' -> total_liabilities; explicit 'total equity /
  shareholders' funds' -> total_equity.""",
    DocumentType.PROFIT_AND_LOSS: STATEMENT_COMMON + """
Profit & loss specifics (use section 'other'). canonical_key mapping:
- Interest earned -> interest_earned; Other income -> other_income; the Total under INCOME -> total_income
- Interest expended -> interest_expended; Operating expenses -> operating_expenses;
  Provisions and contingencies -> provisions_and_contingencies; the Total under EXPENDITURE -> total_expenditure
- The profit row just BEFORE the "Less: Minority interest" row (e.g. "Net profit for the year", "Consolidated Net
  Profit before minorities' interest") -> profit_before_minority_interest;
  Less: Minority interest -> minority_interest;
  Add: Share in profits of associates -> share_in_profit_of_associates;
  Profit attributable to the group -> net_profit_attributable_to_group;
  Impact on amalgamation -> impact_on_amalgamation;
  Balance / Add: Brought forward profit -> brought_forward_profit;
  the Total at the end of the PROFIT section (before APPROPRIATIONS) -> total_available_for_appropriation
- Other layouts: Revenue -> revenue; Cost of sales/COGS -> cost_of_sales; Gross profit -> gross_profit;
  Operating profit -> operating_profit; Income tax -> tax; Net profit -> net_profit.""",
    DocumentType.CASH_FLOW_STATEMENT: STATEMENT_COMMON + """
Cash flow specifics (use section 'other'). canonical_key mapping:
- Net cash from/(used in) operating activities -> operating_cash_flow; investing activities -> investing_cash_flow;
  financing activities -> financing_cash_flow
- Effect of exchange rate / translation adjustment -> fx_adjustment
- Net increase/(decrease) in cash and cash equivalents -> net_change_in_cash
- Cash and cash equivalents at the BEGINNING of the year -> opening_cash; at the END -> closing_cash
- Cash and cash equivalents on amalgamation / other adjustments -> cash_acquired_on_amalgamation
- The statement may span 2 pages: capture rows from BOTH pages and use the same period labels for all rows.""",
}

_SCHEMAS = {
    DocumentType.INVOICE: InvoiceExtraction,
    DocumentType.BALANCE_SHEET: StatementExtraction,
    DocumentType.PROFIT_AND_LOSS: StatementExtraction,
    DocumentType.CASH_FLOW_STATEMENT: StatementExtraction,
}


def schema_model(document_type: DocumentType):
    return _SCHEMAS[document_type]


def build_prompt(document_type: DocumentType) -> str:
    hints = INVOICE_HINTS if document_type == DocumentType.INVOICE else HINTS[document_type]
    schema = json.dumps(schema_model(document_type).model_json_schema(), separators=(",", ":"))
    return f"{hints}\n\nJSON schema to follow exactly:\n{schema}\n\nRead the attached document and return the JSON now."

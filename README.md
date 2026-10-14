# Document Intelligence Platform

Upload an **invoice, balance sheet, profit & loss statement or cash-flow statement** (PDF / JPG / PNG, ≤ 3 pages).
The service validates the file, extracts **all visible fields and tables** with a vision LLM, cross-checks the values
against an independent OCR pass, runs **deterministic financial validations**, stores the result in a database and
exposes it through a **REST API** and an **HTML dashboard**.

| | URL |
|---|---|
| Frontend (dashboard) | `<ADD_DEPLOYED_URL>` |
| Backend API base | `<ADD_DEPLOYED_URL>/api/v1` |
| Swagger / OpenAPI | `<ADD_DEPLOYED_URL>/docs` |
| Health | `<ADD_DEPLOYED_URL>/api/v1/health` |
| GitHub | `<ADD_REPO_URL>` |

## 1. Architecture

```
Browser (HTML/CSS/JS) ──► FastAPI ─► routes/documents.py
                                        │
                              services/document_service.py  (orchestrator)
        ┌──────────────┬─────────────────┼───────────────────┬────────────────────────┐
        ▼              ▼                 ▼                   ▼                        ▼
 document_validation  ocr_service   extraction_service   financial_validation   repositories/
 (magic bytes, size,  (PDF text     (Gemini → JSON →     (pure Python,          document_repository
  corruption, pages)   layer or      Pydantic →           no LLM; PASS/FAIL/     (SQLAlchemy →
                       Tesseract)    normalized dict)     NOT_APPLICABLE)        SQLite / Postgres)
                          │               ▲
                          └─ OCR text ────┴──► utils/confidence.py (grounding score)
```

Flow: `upload → file validation → OCR/text layer → LLM extraction → structured JSON → financial validation →
evidence + confidence → store → PASS/FAILED → dashboard + API`.

Diagram: [`docs/architecture.png`](docs/architecture.png). Code layout follows the required structure
(`backend/app/{api,core,models,schemas,services,repositories,utils}`, `frontend/`, `docs/`, `sample_outputs/`, `tests/`).

## 2. Technology stack and why

| Choice | Reason |
|---|---|
| **FastAPI** | Typed request handling, automatic Swagger/OpenAPI, multipart upload support. |
| **Gemini (`gemini-2.5-flash`, configurable)** | Free tier; reads PDFs and images directly, so scanned statements and receipts need no separate OCR step. Behind an `LLMClient` interface, so another provider can be swapped in without touching the pipeline. |
| **Pydantic schemas** | Every model answer is validated; invalid output is re-asked once, then fails cleanly. |
| **Tesseract + PDF text layer** | Independent text source used only to *cross-check* the LLM (confidence), not as the primary extractor. |
| **SQLAlchemy + SQLite / Postgres** | SQLite locally; Postgres (e.g. Neon free tier) in production because free web hosts wipe local files. |
| **Plain HTML/CSS/JS (Jinja shell)** | Required by the brief; DOM is built with `textContent`, so document text can never inject markup. |

## 3. Local setup

```bash
git clone <ADD_REPO_URL> && cd <repo>
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
# Tesseract (optional but needed for confidence scores):  sudo apt install tesseract-ocr   |  brew install tesseract
cp .env.example backend/.env                                # then set GEMINI_API_KEY
cd backend && uvicorn app.main:app --reload
```

Open http://localhost:8000 (dashboard) and http://localhost:8000/docs (Swagger).
Get a free Gemini key at https://aistudio.google.com. Without `GEMINI_API_KEY` the app still starts; processing returns a
controlled `LLM_NOT_CONFIGURED` error.

Tests: `cd backend && python -m pytest -q`. To include the real-sample tests:
`SAMPLES_DIR="/path/to/New Dataset" python -m pytest -q`.

## 4. Environment variables (`.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | – | LLM key (**secret**, never committed) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model name |
| `DATABASE_URL` | `sqlite:///./data/documents.db` | SQLAlchemy URL; `postgres://…` is accepted too |
| `MAX_PAGES` / `MAX_FILE_SIZE_MB` | `3` / `10` | Input limits |
| `TOLERANCE_STATEMENT` | `1.0` | Absolute tolerance for statement checks (document units) |
| `TOLERANCE_INVOICE` | `0.05` | Absolute tolerance for invoice checks |
| `LLM_TIMEOUT_SECONDS` | `90` | Model call timeout |
| `LOG_LEVEL` | `INFO` | Logging level |

## 5. API

Swagger: `/docs`. All errors use one shape: `{"error": {"code": "...", "message": "..."}}` and never include stack traces.

```bash
# Upload + process (document_type: invoice | balance_sheet | profit_and_loss | cash_flow_statement)
curl -X POST $BASE/api/v1/documents/process -F "file=@receipt.jpg" -F "document_type=invoice"

# Latest stored result by document name
curl "$BASE/api/v1/documents/receipt.jpg"

# Dashboard list (optional: q, document_type, status=PASS|FAILED, limit, offset)
curl "$BASE/api/v1/documents?q=receipt&status=PASS"

# Health
curl $BASE/api/v1/health
```

| Status | Code | When |
|---|---|---|
| 400 | `EMPTY_FILE` | Zero-byte upload |
| 413 | `FILE_TOO_LARGE` | Over `MAX_FILE_SIZE_MB` |
| 415 | `UNSUPPORTED_FILE_TYPE` | Not PDF/JPG/PNG (detected from file content, not the extension) |
| 422 | `CORRUPTED_FILE`, `PAGE_LIMIT_EXCEEDED`, `INVALID_REQUEST` | Unreadable file, >3 pages, bad/missing form field |
| 404 | `DOCUMENT_NOT_FOUND` | Unknown name on GET |
| 502/503/504 | `EXTRACTION_FAILED`, `EXTRACTION_INVALID_OUTPUT`, `LLM_*` | Model errors, rate limits, timeouts |
| 500 | `INTERNAL_ERROR` / `DATABASE_ERROR` | Unexpected failures (details only in server logs) |

**Response** (success, abbreviated): `document_name`, `document_type`, `processing_status` (`PASS`/`FAILED`),
`overall_confidence`, `file_validation`, `extracted_data`, `validation` (`checks[]`, `overall_status`, `issues[]`,
`missing_required_fields`, `low_confidence_fields`), `processing_metadata` (`ocr_used`, `model`, `processed_at`,
`processing_time_ms`).

* **Invoices** — each field is `{value, confidence, page_number, source_text}`; `line_items[]` has
  `description, quantity, unit_price, amount, tax_code`.
* **Statements** — header fields, `periods[]`, `line_items[]` (every row with `row_type`, `section`, `values{period: number}`,
  `raw_values`, evidence), and `key_figures{canonical_key: {period: number}}` for the required minimum fields.
* Missing values are `null`; nothing is inferred.

`processing_status` is `PASS` when the file is valid, extraction succeeded and no financial check **FAILs**; otherwise
`FAILED` (invalid/corrupt/unsupported file, model failure, or a failed reconciliation). Missing optional fields are
reported under `validation.missing_required_fields` and highlighted, but do not by themselves fail the document.
Failed attempts are also stored, so they appear in the dashboard.

## 6. Extraction approach

1. The file bytes are sent to Gemini with a per-type prompt and the Pydantic JSON schema (temperature 0).
2. Rules: extract only what is visible, never calculate or guess, brackets ⇒ negative, `null` when absent, always
   return a verbatim `source_text` and `page_number`.
3. For statements the model tags each row with a `row_type` (item/subtotal/total/heading), a `section`
   (assets / capital_and_liabilities) and, when unambiguous, a `canonical_key` (e.g. `total_income`).
   Validation uses these tags, so it works regardless of the wording in the document.
4. Output is parsed with Pydantic; on invalid JSON the model is asked once more with the error, then the request
   fails with `EXTRACTION_INVALID_OUTPUT`.

## 7. Financial validation (no LLM)

Tolerance: a check passes when `|calculated − reported| ≤ tolerance` (statements `1.0`, in document units, because
statements in crore/millions carry rounding drift; invoices `0.05` to allow 5-sen cash rounding). Each check returns
`name, formula, operands, calculated_value, reported_value, variance, tolerance, status`, plus `period` for statements.
If an input is missing the status is **NOT_APPLICABLE** — nothing is assumed.

| Type | Checks (per period/year) |
|---|---|
| Invoice | `qty × unit_price = line amount`; Σ lines vs subtotal (or vs total when prices include tax); `subtotal + tax − discount + rounding = total` (falls back to the tax-inclusive reading when the document says tax is included); `cash − total = change` |
| Balance sheet | `total_assets = total_capital_and_liabilities`; Σ asset items = total assets; Σ capital & liability items = total |
| P&L | `interest_earned + other_income = total_income`; `interest_expended + operating_expenses + provisions = total_expenditure`; `income − expenditure = profit before minority interest`; `− minority interest = profit attributable to group`; `+ brought forward = total available for appropriation` (+ generic `revenue − cost_of_sales = gross_profit`) |
| Cash flow | `operating + investing + financing (+ FX if shown) = net change`; `opening + net change (+ amalgamation cash if shown) = closing` |

## 8. Confidence (optional feature) — how it is computed

Not an LLM self-rating. After extraction, an **independent** text source (PDF text layer, or Tesseract for scans/images)
is searched for each value:

`confidence = 0.60 + 0.35 × (share of the value's parts found in the independent OCR text)`

* found → **0.95**; not found → **0.60** (flagged *low*, threshold `< 0.80`); null value or no OCR → no score.
* `overall_confidence` is the mean of all scores. Limitation: OCR itself can miss stamps/handwriting, so "low" means
  *not corroborated*, not *wrong*.

## 9. Persistence

`documents` table: `id, document_name (indexed), document_type, processing_status, validation_status,
overall_confidence, processing_time_ms, processed_at, result (JSON)`. Every run inserts a row (history is kept).
`GET /documents/{name}` returns the newest row; the dashboard lists rows newest-first with search/filters.
Uploaded files are processed in memory and **not** written to disk.

## 10. Deployment (Render + Neon Postgres)

1. Create a free Postgres at neon.tech and copy its connection string.
2. Push this repo to GitHub (public).
3. On render.com: **New → Blueprint** → select the repo (uses `render.yaml`, a Docker web service).
4. In the service's *Environment* tab set `GEMINI_API_KEY` and `DATABASE_URL` (the Neon URL).
5. Deploy; check `/api/v1/health`, `/docs` and the dashboard. The free tier sleeps when idle — open the URL once
   before the evaluation (first request can take ~30–60 s).

## 11. Testing

`backend/tests/` — file validation (valid, empty, unsupported, renamed, corrupted, page limit), financial calculations
(pass, fail, NOT_APPLICABLE, per-period, tax-inclusive receipts), extraction/normalization/confidence, and API flows
(process, GET latest, list/search, 415/400/422/404/502/500 error shapes, retry on invalid model JSON, DB persistence).
The model is faked in tests, so the suite is deterministic and needs no API key.

`scripts/run_samples.py` sends the sample dataset to a running API and writes the real responses to `sample_outputs/`
(including a validation-failure/unsupported-file case).

## 12. Known limitations

* Accuracy depends on the vision model; handwriting, stamps and very low-resolution scans may be misread (this is what
  the confidence flag is for).
* Processing is synchronous (typically 5–40 s per document) — fine for ≤ 3 pages, not for bulk loads.
* Free tiers: Gemini rate limits, Render cold starts.
* The first value of a repeated `canonical_key` per period wins (e.g. two "Total" rows tagged identically).
* No authentication or per-user data isolation; the uploaded file is not retained.
* Tolerance is absolute, not relative; very large or very small unit scales may need tuning.

## 13. What I would change for production

Authentication and per-tenant storage; async job queue (Celery/RQ) with status polling; object storage for originals
with a viewer that highlights the evidence region; relative + unit-aware tolerances; schema-versioned prompts with an
evaluation set measuring field-level accuracy; model fallback chain and caching; DB migrations (Alembic);
structured JSON logs, metrics and tracing; rate limiting; malware scanning of uploads.

## 14. AI / tool usage declaration

> **Edit this section so it is accurate for you.**
> Claude (Anthropic) was used as a coding assistant to scaffold the project, draft the services, tests, frontend and
> documentation, and to debug. Gemini is used at runtime for extraction. I reviewed, ran and can explain all code.

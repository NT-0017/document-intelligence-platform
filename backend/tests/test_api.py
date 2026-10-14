import glob
import io
import os

import pytest
from fastapi.testclient import TestClient

from app.api.routes.documents import get_extractor
from app.core.exceptions import ExtractionError
from app.main import app
from app.services.extraction_service import ExtractionService
from tests.fakes import FakeLLM, pl_json, receipt_json

SAMPLES = os.environ.get("SAMPLES_DIR", "")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def use_llm(llm):
    app.dependency_overrides[get_extractor] = lambda: ExtractionService(llm)


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def post(client, name, content, doc_type="invoice", mime="application/pdf"):
    return client.post("/api/v1/documents/process", files={"file": (name, io.BytesIO(content), mime)},
                       data={"document_type": doc_type})


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_process_invoice_end_to_end(client, image_bytes):
    use_llm(FakeLLM(receipt_json()))
    r = post(client, "receipt_a.png", image_bytes("PNG"), mime="image/png")
    assert r.status_code == 200
    body = r.json()
    assert body["processing_status"] == "PASS"
    assert body["file_validation"]["status"] == "PASS" and body["file_validation"]["page_count"] == 1
    assert body["extracted_data"]["total_amount"]["value"] == 30.30
    assert body["validation"]["overall_status"] == "PASS"
    assert {"ocr_used", "processed_at", "processing_time_ms", "model"} <= set(body["processing_metadata"])
    assert "error_code" not in body["file_validation"]


def test_get_by_name_returns_latest_and_list_shows_it(client, image_bytes):
    use_llm(FakeLLM(receipt_json(total=30.30)))
    post(client, "dup.png", image_bytes("PNG"), mime="image/png")
    use_llm(FakeLLM(receipt_json(total=31.00)))
    post(client, "dup.png", image_bytes("PNG"), mime="image/png")
    got = client.get("/api/v1/documents/dup.png").json()
    assert got["extracted_data"]["total_amount"]["value"] == 31.00  # latest wins
    listing = client.get("/api/v1/documents", params={"q": "dup"}).json()
    assert listing["total"] == 2 and listing["items"][0]["document_name"] == "dup.png"


def test_financial_validation_failure_marks_failed(client, image_bytes):
    use_llm(FakeLLM(receipt_json(change=5.00)))
    body = post(client, "badchange.png", image_bytes("PNG"), mime="image/png").json()
    assert body["processing_status"] == "FAILED"
    assert body["validation"]["overall_status"] == "FAIL" and body["validation"]["issues"]


def test_unsupported_file_returns_415_and_is_recorded(client):
    r = post(client, "notes.txt", b"hello", mime="text/plain")
    assert r.status_code == 415
    assert r.json() == {"error": {"code": "UNSUPPORTED_FILE_TYPE",
                                  "message": "Only PDF / JPG / PNG documents are supported."}}
    failed = client.get("/api/v1/documents", params={"status": "FAILED", "q": "notes"}).json()
    assert failed["total"] >= 1


def test_empty_and_page_limit(client, pdf_bytes):
    assert post(client, "e.pdf", b"").status_code == 400
    r = post(client, "long.pdf", pdf_bytes(4))
    assert r.status_code == 422 and r.json()["error"]["code"] == "PAGE_LIMIT_EXCEEDED"


def test_invalid_document_type_and_missing_file(client, image_bytes):
    r = post(client, "a.png", image_bytes("PNG"), doc_type="passport", mime="image/png")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"
    assert client.post("/api/v1/documents/process", data={"document_type": "invoice"}).status_code == 422


def test_unknown_document_is_404(client):
    r = client.get("/api/v1/documents/does-not-exist.pdf")
    assert r.status_code == 404 and r.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_llm_failure_is_controlled_error_without_stack_trace(client, image_bytes):
    use_llm(FakeLLM(error=ExtractionError("The extraction model request failed.", "LLM_REQUEST_FAILED", 502)))
    r = post(client, "llmfail.png", image_bytes("PNG"), mime="image/png")
    assert r.status_code == 502 and r.json()["error"]["code"] == "LLM_REQUEST_FAILED"
    assert "Traceback" not in r.text


def test_unexpected_error_hides_details(client, image_bytes):
    use_llm(FakeLLM(error=RuntimeError("secret-internal-detail")))
    r = post(client, "boom.png", image_bytes("PNG"), mime="image/png")
    assert r.status_code == 500 and "secret-internal-detail" not in r.text


def test_invalid_llm_json_is_retried_once(client, image_bytes):
    import json
    llm = FakeLLM(raw=["not json at all", json.dumps(receipt_json())])
    use_llm(llm)
    r = post(client, "retry.png", image_bytes("PNG"), mime="image/png")
    assert r.status_code == 200 and llm.calls == 2


def test_persistently_invalid_llm_json_fails_cleanly(client, image_bytes):
    use_llm(FakeLLM(raw="{{{"))
    r = post(client, "garbage.png", image_bytes("PNG"), mime="image/png")
    assert r.status_code == 502 and r.json()["error"]["code"] == "EXTRACTION_INVALID_OUTPUT"


@pytest.mark.skipif(not SAMPLES, reason="set SAMPLES_DIR to the extracted 'New Dataset' folder")
def test_real_scanned_pdf_pl_with_ocr_confidence(client):
    use_llm(FakeLLM(pl_json()))
    f = glob.glob(f"{SAMPLES}/Profit & Loss/*2023.pdf")[0]
    body = post(client, "pl_2023.pdf", open(f, "rb").read(), "profit_and_loss").json()
    assert body["processing_status"] == "PASS" and body["processing_metadata"]["ocr_used"] is True
    assert body["overall_confidence"] and body["overall_confidence"] > 0.85
    assert body["validation"]["overall_status"] == "PASS" and len(body["validation"]["checks"]) == 10


@pytest.mark.skipif(not SAMPLES, reason="set SAMPLES_DIR to the extracted 'New Dataset' folder")
def test_real_receipt_image_flags_value_ocr_cannot_corroborate(client):
    use_llm(FakeLLM(receipt_json()))
    f = f"{SAMPLES}/Invoices/X51005663293.jpg"
    body = post(client, "X51005663293.jpg", open(f, "rb").read(), "invoice", "image/jpeg").json()
    assert body["processing_status"] == "PASS" and body["extracted_data"]["total_amount"]["confidence"] >= 0.9

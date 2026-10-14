from app.services.document_validation_service import validate_file


def test_valid_pdf(pdf_bytes):
    r = validate_file("a.pdf", pdf_bytes(1))
    assert r.status == "PASS" and r.page_count == 1 and r.file_type == "application/pdf"


def test_valid_png_and_jpg(image_bytes):
    assert validate_file("a.png", image_bytes("PNG")).status == "PASS"
    r = validate_file("a.jpg", image_bytes("JPEG"))
    assert r.status == "PASS" and r.file_type == "image/jpeg"


def test_empty_file():
    r = validate_file("a.pdf", b"")
    assert r.status == "FAIL" and r.error_code == "EMPTY_FILE"


def test_unsupported_type():
    r = validate_file("a.txt", b"hello world")
    assert r.error_code == "UNSUPPORTED_FILE_TYPE" and not r.is_supported


def test_renamed_file_detected_by_content():
    # a text file renamed .pdf is still rejected
    assert validate_file("fake.pdf", b"not really a pdf").error_code == "UNSUPPORTED_FILE_TYPE"


def test_corrupted_pdf():
    r = validate_file("a.pdf", b"%PDF-1.4\n garbage garbage")
    assert r.status == "FAIL" and r.error_code == "CORRUPTED_FILE"


def test_corrupted_png():
    r = validate_file("a.png", b"\x89PNG\r\n\x1a\n" + b"junk")
    assert r.error_code == "CORRUPTED_FILE"


def test_page_limit(pdf_bytes):
    assert validate_file("a.pdf", pdf_bytes(3)).status == "PASS"
    r = validate_file("a.pdf", pdf_bytes(4))
    assert r.error_code == "PAGE_LIMIT_EXCEEDED" and r.page_count == 4

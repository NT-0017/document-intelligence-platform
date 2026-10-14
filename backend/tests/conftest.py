import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import pytest
from PIL import Image
from pypdf import PdfWriter


def make_pdf(pages: int = 1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_image(fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def pdf_bytes():
    return make_pdf


@pytest.fixture
def image_bytes():
    return make_image

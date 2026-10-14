"""Explainable confidence: agreement between the LLM-read value and an independent OCR pass.

For each extracted value we check whether it can be found in the independent OCR/text-layer
output of the same document:
    confidence = 0.60 + 0.35 * (share of the value's parts corroborated by OCR)
  * corroborated        -> 0.95
  * not found in OCR    -> 0.60 (read by the LLM only; highlighted as low confidence < 0.70)
  * null value / no OCR -> no score (None)
This is not an LLM self-rating. Its limit: OCR itself can miss text (stamps, handwriting).
"""
import re
from statistics import mean

BASE, SPAN = 0.60, 0.35
LOW_CONFIDENCE_THRESHOLD = 0.70

_NUM = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def numbers_in(text: str) -> set[float]:
    found: set[float] = set()
    for tok in _NUM.findall(text):
        t = tok.strip("()").replace("-", "")
        candidates = {t.replace(",", "")}
        if re.search(r",\d{1,2}$", t):  # decimal comma written by OCR, e.g. "1,72"
            candidates.add(t.replace(",", "."))
        for c in candidates:
            try:
                found.add(round(abs(float(c)), 2))
            except ValueError:
                continue
    return found


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def text_grounded(value: str, text: str, nums: set[float]) -> bool:
    m = _ISO_DATE.match(value.strip())
    if m:  # ISO date produced by the LLM vs d-m-y / d/m/y printed on the page
        y, mo, d = m.groups()
        flat = re.sub(r"\D+", " ", text)
        return y in flat and int(mo) in {int(x) for x in re.findall(r"\b\d{1,2}\b", flat)} and int(d) in {
            int(x) for x in re.findall(r"\b\d{1,2}\b", flat)}
    nv, nt = _norm(value), _norm(text)
    if not nv:
        return False
    if nv in nt:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]+", value.lower()) if len(t) >= 3]
    if not tokens:
        return False
    return sum(1 for t in tokens if t in nt) / len(tokens) >= 0.8


def score(frac: float) -> float:
    return round(BASE + SPAN * frac, 2)


def _scalar(field: dict, text: str, nums: set[float]) -> None:
    v = field.get("value")
    if v is None or isinstance(v, bool):
        field["confidence"] = None
        return
    ok = round(abs(float(v)), 2) in nums if isinstance(v, (int, float)) else text_grounded(str(v), text, nums)
    field["confidence"] = score(1.0 if ok else 0.0)


def apply_confidence(data: dict, ocr_text: str) -> float | None:
    """Annotate `data` in place with confidence; return the overall (mean) or None."""
    if not ocr_text.strip():
        return None
    nums, scores = numbers_in(ocr_text), []

    for key, f in data.items():
        if isinstance(f, dict) and "value" in f:
            _scalar(f, ocr_text, nums)
            if f["confidence"] is not None:
                scores.append(f["confidence"])

    for li in data.get("line_items", []):
        parts = []
        if "values" in li:  # statement row
            parts = [round(abs(v), 2) in nums for v in li["values"].values() if v is not None]
        else:  # invoice row
            for k in ("quantity", "unit_price", "amount"):
                if li.get(k) is not None:
                    parts.append(round(abs(li[k]), 2) in nums)
            if li.get("description"):
                parts.append(text_grounded(li["description"], ocr_text, nums))
        li["confidence"] = score(sum(parts) / len(parts)) if parts else None
        if li["confidence"] is not None:
            scores.append(li["confidence"])
    return round(mean(scores), 2) if scores else None

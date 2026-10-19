"""Tolerant number parsing for model output. Brackets / trailing minus mean negative."""
import re

_EMPTY = {"", "-", "–", "—", "nil", "null", "none", "n/a", "na"}


def to_number(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.lower() in _EMPTY:
        return None
    negative = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.endswith("-")
    cleaned = re.sub(r"[^\d.,]", "", s)
    if not cleaned:
        return None
    if "," in cleaned and "." not in cleaned and re.search(r",\d{1,2}$", cleaned):
        cleaned = cleaned.replace(",", ".")  # decimal comma, e.g. "1,72"
    else:
        cleaned = cleaned.replace(",", "")
    try:
        x = float(cleaned)
    except ValueError:
        return None
    return -x if negative else x


def to_int(v) -> int | None:
    n = to_number(v)
    return int(n) if n is not None else None

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag


_HEADER_KEYS = {
    "written",
    "source",
    "first published",
    "published",
    "translated",
    "translation",
    "transcription",
    "transcription/html markup",
    "transcription/markup",
    "transcription/mark-up",
    "markup",
    "mark-up",
    "public domain",
    "copyleft",
    "copyright",
    "notes",
}


def extract_marxists_header_metadata(html: str) -> dict[str, Any] | None:
    """
    Extract marxists.org header metadata (e.g., Written/Source/First Published/Translated/...).

    Returns a dict with:
      - fields: { "Written": "...", "Source": "...", ... }
      - dates:  { "written": {...}|None, "first_published": {...}|None, "published": {...}|None }
      - editorial_intro: optional list[str]
      - extracted_at: ISO timestamp
    """
    soup = BeautifulSoup(html, "lxml")
    container = soup.find("div", id="content") or soup.find("div", class_="article") or soup.body
    if not isinstance(container, Tag):
        return None

    info_blocks: list[Tag] = []
    for p in container.find_all("p"):
        classes = set(p.get("class") or [])
        if "information" in classes:
            info_blocks.append(p)
            continue
        # Some pages use spans without the information class; include any paragraph that looks like a header KV list.
        if p.find("span", class_="info") and _looks_like_header_kv(p):
            info_blocks.append(p)

    fields: dict[str, str] = {}
    for p in info_blocks:
        extracted = _extract_fields_from_information_paragraph(p)
        for k, v in extracted.items():
            if k not in fields and v:
                fields[k] = v

    # Editorial intro is often marked with class "intro" and contains an editor note.
    editorial_intro: list[str] = []
    for p in container.find_all("p", class_=re.compile(r"\bintro\b")):
        text = p.get_text(" ", strip=True)
        if text:
            editorial_intro.append(_clean_ws(text))

    if not fields and not editorial_intro:
        return None

    return {
        "fields": fields,
        "dates": {
            "written": parse_dateish(fields.get("Written")),
            "first_published": parse_dateish(fields.get("First Published")),
            "published": parse_dateish(fields.get("Published")),
        },
        "editorial_intro": editorial_intro or None,
        "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _looks_like_header_kv(p: Tag) -> bool:
    spans = p.find_all("span", class_="info")
    for s in spans[:6]:
        label = _clean_ws(s.get_text(" ", strip=True)).rstrip(":").lower()
        if label in _HEADER_KEYS:
            return True
    text = _clean_ws(p.get_text(" ", strip=True)).lower()
    return any(text.startswith(f"{k}:") for k in _HEADER_KEYS)


def _extract_fields_from_information_paragraph(p: Tag) -> dict[str, str]:
    """
    Parse a `<p class="information">` block into key/value fields.
    Prefers `<span class="info">Key:</span>` formatting.
    """
    out: dict[str, str] = {}

    spans = p.find_all("span", class_="info")
    if spans:
        for span in spans:
            key_raw = _clean_ws(span.get_text(" ", strip=True)).rstrip(":")
            if not key_raw:
                continue
            # Ignore numeric footnote markers like "1.".
            if re.fullmatch(r"\d+\.?", key_raw.strip()):
                continue

            key = key_raw
            value = _text_until_break(span)
            value = _clean_ws(value)
            value = value.lstrip(" :")
            if not value:
                continue

            # Canonicalize common variants.
            if key.lower() in {
                "transcription/html markup",
                "transcription\\html markup",
                "transcription\\markup",
                "transcription/markup",
                "transcription/mark-up",
            }:
                key = "Transcription/Markup"

            out[key] = value
        return out

    # Fallback: "Written: ..." style without spans.
    text = _clean_ws(p.get_text(" ", strip=True))
    m = re.match(r"^([A-Za-z][A-Za-z /\\\\-]{2,40}):\s*(.+)$", text)
    if m:
        out[m.group(1).strip()] = m.group(2).strip()
    return out


def _text_until_break(span: Tag) -> str:
    """
    Collect sibling text after `span` until the next <br/> or another <span class="info">.
    """
    parts: list[str] = []
    for sib in span.next_siblings:
        if isinstance(sib, Tag):
            if sib.name == "br":
                break
            if sib.name == "span" and "info" in set(sib.get("class") or []):
                break
            parts.append(sib.get_text(" ", strip=True))
        elif isinstance(sib, NavigableString):
            parts.append(str(sib))
    return "".join(parts)


_YEAR_RE = re.compile(r"(?<!\d)(1[5-9]\d{2}|20[0-3]\d)(?!\d)")
_DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(1[5-9]\d{2}|20[0-3]\d)\b"
)
_MONTH_DAY_YEAR_RE = re.compile(
    r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*,\s*(1[5-9]\d{2}|20[0-3]\d)\b"
)


def parse_dateish(value: str | None) -> dict[str, Any] | None:
    """
    Best-effort parse of a human-readable date string into {year, month, day, precision}.
    We keep this conservative: if we can't find a plausible year, return None.
    """
    if not value:
        return None
    v = _clean_ws(value)

    m = _DAY_MONTH_YEAR_RE.search(v)
    if m:
        day = int(m.group(1))
        month = _month_to_int(m.group(2))
        year = int(m.group(3))
        if month is not None:
            return {"year": year, "month": month, "day": day, "precision": "day", "raw": v}

    m = _MONTH_DAY_YEAR_RE.search(v)
    if m:
        month = _month_to_int(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3))
        if month is not None:
            return {"year": year, "month": month, "day": day, "precision": "day", "raw": v}

    m = _YEAR_RE.search(v)
    if not m:
        return None
    year = int(m.group(1))
    return {"year": year, "month": None, "day": None, "precision": "year", "raw": v}


def _month_to_int(name: str) -> int | None:
    n = name.strip().lower()
    mapping = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    return mapping.get(n)


def _clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

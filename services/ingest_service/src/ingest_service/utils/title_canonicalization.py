from __future__ import annotations

import re

_SMALL_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "nor",
    "but",
    "for",
    "so",
    "yet",
    "as",
    "at",
    "by",
    "in",
    "of",
    "on",
    "to",
    "from",
    "with",
    "over",
    "under",
    "into",
    "onto",
    "upon",
}

_ROMAN_RE = re.compile(r"^(?=[IVXLCDM]+$)[IVXLCDM]+$", re.IGNORECASE)

_KNOWN_ACRONYMS = {
    "US",
    "USA",
    "UK",
    "UN",
    "EU",
    "USSR",
    "CIA",
    "FBI",
    "NATO",
    "NAFTA",
}


def canonicalize_title(title: str) -> str:
    """
    Produce a standardized display title without changing Work identity.

    Policy:
    - Always normalize whitespace.
    - Only apply title-casing when the input is "mostly uppercase" (common marxists.org formatting),
      to avoid damaging legitimate casing.
    """
    normalized = _normalize_whitespace(title)
    if not normalized:
        return normalized

    if not _is_mostly_uppercase(normalized):
        return normalized

    return _title_case_englishish(normalized)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_mostly_uppercase(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 6:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    lower = sum(1 for ch in letters if ch.islower())
    if lower == 0 and upper >= 6:
        return True
    return upper / max(1, (upper + lower)) >= 0.7


def _title_case_englishish(text: str) -> str:
    # Tokenize into word vs non-word, preserving punctuation/spaces.
    tokens = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?|[^A-Za-z0-9]+", text)
    words = [t for t in tokens if re.match(r"[A-Za-z0-9]", t)]
    if not words:
        return text

    # Identify first/last word token positions among all tokens.
    word_positions = [i for i, t in enumerate(tokens) if re.match(r"[A-Za-z0-9]", t)]

    def is_casing_word(tok: str) -> bool:
        return any(ch.isalpha() for ch in tok)

    # If the title starts with a numeric index (e.g., "579. TO THE ..."), treat the first
    # alphabetic token as the "first word" for capitalization rules.
    first_word_pos = next((i for i in word_positions if is_casing_word(tokens[i])), word_positions[0])
    last_word_pos = next((i for i in reversed(word_positions) if is_casing_word(tokens[i])), word_positions[-1])

    out: list[str] = []
    for i, tok in enumerate(tokens):
        if not re.match(r"[A-Za-z0-9]", tok):
            out.append(tok)
            continue

        # Keep numeric tokens as-is.
        if tok.isdigit():
            out.append(tok)
            continue

        # Preserve roman numerals.
        if _ROMAN_RE.match(tok):
            out.append(tok.upper())
            continue

        lower = tok.lower()
        if i not in (first_word_pos, last_word_pos) and lower in _SMALL_WORDS:
            out.append(lower)
            continue

        # Preserve known acronyms/initialisms.
        if tok.isupper() and (tok in _KNOWN_ACRONYMS or any(ch.isdigit() for ch in tok)):
            out.append(tok)
            continue

        out.append(lower[:1].upper() + lower[1:])

    return "".join(out)

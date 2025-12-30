from __future__ import annotations

import re

def split_paragraph_into_sentences(language: str, paragraph_text: str) -> list[str]:
    """
    Day-1 contract:
    - Deterministic sentence splitting per language.
    - LLM fallback only for pathological cases (later).
    """
    text = paragraph_text.strip()
    if not text:
        return []

    # Conservative, deterministic splitter:
    # - splits on .!? followed by whitespace and a likely sentence start
    # - keeps delimiters in the sentence
    # This is intentionally simple; it will be replaced with a language-aware splitter later.
    boundary = re.compile(r"(?<=[.!?])\s+(?=[\"'“”‘’(]*[A-Z0-9])")
    parts = boundary.split(text)

    # Normalize whitespace per sentence but preserve content.
    sentences = [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]
    return sentences

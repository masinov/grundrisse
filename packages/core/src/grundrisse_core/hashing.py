from __future__ import annotations

from hashlib import sha256


def sha256_hex(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


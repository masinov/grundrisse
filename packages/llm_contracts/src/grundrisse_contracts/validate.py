from __future__ import annotations

from typing import Any

import jsonschema


class ValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def validate_json(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:  # pragma: no cover
        raise ValidationError(str(exc)) from exc


def assert_target_only_sentence_indices(
    evidence_sentence_indices: list[int],
    target_sentence_count: int,
) -> None:
    for idx in evidence_sentence_indices:
        if idx < 0 or idx >= target_sentence_count:
            raise ValidationError(
                f"evidence_sentence_indices contains out-of-range index {idx} "
                f"for TARGET sentence_count={target_sentence_count}"
            )

from __future__ import annotations

from typing import Any

from grundrisse_contracts.validate import assert_target_only_sentence_indices, validate_json


def validate_a3_claims_output(
    output: dict[str, Any],
    schema: dict[str, Any],
    *,
    target_sentence_count: int,
) -> None:
    validate_json(output, schema)
    for claim in output.get("claims", []):
        assert_target_only_sentence_indices(
            evidence_sentence_indices=claim.get("evidence_sentence_indices", []),
            target_sentence_count=target_sentence_count,
        )


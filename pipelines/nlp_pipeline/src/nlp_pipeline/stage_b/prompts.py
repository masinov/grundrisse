from __future__ import annotations

import json
from typing import Any


def render_b_prompt(*, payload: dict[str, Any], schema: dict[str, Any]) -> str:
    """
    Prompt for concept canonicalization ("Ontologist").
    Keep it short and structured; rely on response_format + schema validation.
    """
    return (
        "Task: Canonicalize concept mentions into one or more Concepts (split senses conservatively).\n"
        "Rules:\n"
        "- Work within this cluster only.\n"
        "- Prefer splitting distinct senses over merging.\n"
        "- Output keys must EXACTLY match the schema (no extra punctuation like 'gloss:').\n"
        "- Always include a 1–2 sentence `gloss` for every concept.\n"
        "- Every returned concept must include assigned_mention_ids.\n"
        "- Return ONLY JSON matching the schema.\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def render_b_repair_prompt(
    *,
    payload: dict[str, Any],
    schema: dict[str, Any],
    validation_error: str,
    prior_output: str,
) -> str:
    """
    Repair prompt used when the model returned invalid JSON or schema-nonconformant output.
    Keep it very explicit: JSON only, exact keys, and include the validation error.
    """
    prior_snippet = prior_output.strip()
    if len(prior_snippet) > 1500:
        prior_snippet = prior_snippet[:1500] + "…"
    return (
        "Your previous response did NOT conform to the JSON schema.\n"
        "You MUST return ONLY valid JSON that matches the schema exactly.\n"
        "Do not add punctuation to keys (e.g., do not output 'gloss:').\n"
        "Validation error:\n"
        f"{validation_error}\n\n"
        "SCHEMA:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "INPUT (same as before):\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "YOUR PRIOR OUTPUT (for reference; do not repeat unless it matches schema):\n"
        f"{prior_snippet}\n"
    )

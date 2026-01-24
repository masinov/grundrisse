"""Validation constraints and checks.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §12:

Hard Constraints (must pass):
- Span grounding: All propositions cite existing locutions
- AIF validity: All references point to existing nodes
- Evidence: All relations cite evidence locutions
- No unanchored illocutionary force
- Schema validity: Valid JSON and required fields

Soft Constraints (penalized):
- Cyclic support in small windows
- Conflict between unrelated concepts
- Excessive equivalence clustering
"""

from argument_pipeline.validation.validators import (
    ValidationResult,
    ValidationWarning,
    check_aif_validity,
    check_all,
    check_cycles,
    check_evidence,
    check_grounding,
    check_overgeneration,
    check_schema,
    check_unrelated_conflicts,
    validate_extraction_window,
)

__all__ = [
    "ValidationResult",
    "ValidationWarning",
    "check_aif_validity",
    "check_all",
    "check_cycles",
    "check_evidence",
    "check_grounding",
    "check_overgeneration",
    "check_schema",
    "check_unrelated_conflicts",
    "validate_extraction_window",
]

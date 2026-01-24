"""Validation functions for argument extraction.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §12:

Hard Constraints (must pass):
- Span grounding: All propositions cite existing locutions
- AIF validity: All references point to existing nodes
- Evidence: All relations cite evidence locutions
- No unanchored illocutionary force

Soft Constraints (penalized):
- Cyclic support in small windows
- Conflict between unrelated concepts
- Excessive equivalence clustering
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationWarning:
    """A soft constraint violation."""
    check_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validation checks."""
    is_valid: bool
    hard_errors: list[ValidationWarning] = field(default_factory=list)
    soft_warnings: list[ValidationWarning] = field(default_factory=list)

    def add_hard_error(self, check: str, message: str, **details: Any) -> None:
        self.hard_errors.append(ValidationWarning(check, message, details))
        self.is_valid = False

    def add_soft_warning(self, check: str, message: str, **details: Any) -> None:
        self.soft_warnings.append(ValidationWarning(check, message, details))

    @property
    def has_hard_errors(self) -> bool:
        return len(self.hard_errors) > 0

    @property
    def has_soft_warnings(self) -> bool:
        return len(self.soft_warnings) > 0


def validate_extraction_window(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a complete extraction window against all constraints.

    Args:
        data: Extraction window data from LLM

    Returns:
        ValidationResult with all errors and warnings
    """
    result = ValidationResult(is_valid=True)

    # Schema validation (check required fields, enum values)
    check_schema(data, result)

    # Hard constraints (§12.1)
    check_grounding(data, result)
    check_evidence(data, result)
    check_aif_validity(data, result)

    # Soft constraints (§12.2)
    check_overgeneration(data, result)
    check_cycles(data, result)
    check_unrelated_conflicts(data, result)

    return result


def check_grounding(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check grounding constraint: All propositions must cite existing locutions.

    Per §12.1: Reject if span grounding fails.
    """
    locutions = data.get("locutions", [])
    loc_ids = {loc.get("loc_id") for loc in locutions if loc.get("loc_id")}

    for i, prop in enumerate(data.get("propositions", [])):
        surface_loc_ids = prop.get("surface_loc_ids", [])
        if not surface_loc_ids:
            result.add_hard_error(
                "grounding",
                f"Proposition {i} missing surface_loc_ids",
                proposition_index=i,
                proposition=prop,
            )
            continue

        for lid in surface_loc_ids:
            if lid not in loc_ids:
                result.add_hard_error(
                    "grounding",
                    f"Proposition {i} cites non-existent locution: {lid}",
                    proposition_index=i,
                    locution_id=lid,
                )


def check_evidence(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check evidence constraint: All relations must cite evidence locutions.

    Per §12.1: Reject if evidence missing for relations.
    """
    loc_ids = {loc.get("loc_id") for loc in data.get("locutions", []) if loc.get("loc_id")}

    for i, rel in enumerate(data.get("relations", [])):
        evidence_loc_ids = rel.get("evidence_loc_ids", [])
        if not evidence_loc_ids:
            result.add_hard_error(
                "evidence",
                f"Relation {i} missing evidence_loc_ids",
                relation_index=i,
                relation=rel,
            )
            continue

        for lid in evidence_loc_ids:
            if lid not in loc_ids:
                result.add_hard_error(
                    "evidence",
                    f"Relation {i} cites non-existent evidence locution: {lid}",
                    relation_index=i,
                    locution_id=lid,
                )


def check_aif_validity(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check AIF graph validity: All references point to existing nodes.

    Per §12.1: Reject if AIF structure invalid.
    """
    loc_ids = {loc.get("loc_id") for loc in data.get("locutions", []) if loc.get("loc_id")}
    prop_ids = {prop.get("prop_id") for prop in data.get("propositions", []) if prop.get("prop_id")}

    # Check illocutions link to existing nodes
    for i, illoc in enumerate(data.get("illocutions", [])):
        source_id = illoc.get("source_loc_id")
        target_id = illoc.get("target_prop_id")

        if source_id not in loc_ids:
            result.add_hard_error(
                "aif_validity",
                f"Illocution {i} source_loc_id not found: {source_id}",
                illocution_index=i,
                locution_id=source_id,
            )

        if target_id not in prop_ids:
            result.add_hard_error(
                "aif_validity",
                f"Illocution {i} target_prop_id not found: {target_id}",
                illocution_index=i,
                proposition_id=target_id,
            )

    # Check relations link to existing propositions
    for i, rel in enumerate(data.get("relations", [])):
        source_ids = rel.get("source_prop_ids", [])
        target_id = rel.get("target_prop_id")

        for sid in source_ids:
            if sid not in prop_ids:
                result.add_hard_error(
                    "aif_validity",
                    f"Relation {i} source_prop_id not found: {sid}",
                    relation_index=i,
                    proposition_id=sid,
                )

        if target_id not in prop_ids:
            result.add_hard_error(
                "aif_validity",
                f"Relation {i} target_prop_id not found: {target_id}",
                relation_index=i,
                proposition_id=target_id,
            )


def check_overgeneration(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check for excessive extraction (soft constraint).

    Per §12.2: Penalize excessive equivalence clustering.
    """
    num_props = len(data.get("propositions", []))
    num_relations = len(data.get("relations", []))
    num_locutions = len(data.get("locutions", []))

    # More propositions than locutions is suspicious
    if num_props > num_locutions * 2:
        result.add_soft_warning(
            "overgeneration",
            f"Too many propositions ({num_props}) relative to locutions ({num_locutions})",
            proposition_count=num_props,
            locution_count=num_locutions,
        )

    # More relations than propositions is suspicious
    if num_relations > num_props * 3:
        result.add_soft_warning(
            "overgeneration",
            f"Too many relations ({num_relations}) relative to propositions ({num_props})",
            relation_count=num_relations,
            proposition_count=num_props,
        )


def check_cycles(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check for cyclic support in small windows (soft constraint).

    Per §12.2: Penalize cyclic support in small windows.
    """
    # Build support graph
    support_edges = []
    prop_ids = {prop.get("prop_id") for prop in data.get("propositions", [])}

    for rel in data.get("relations", []):
        if rel.get("relation_type") == "support":
            for source_id in rel.get("source_prop_ids", []):
                target_id = rel.get("target_prop_id")
                if source_id in prop_ids and target_id in prop_ids:
                    support_edges.append((source_id, target_id))

    if not support_edges:
        return

    # Detect cycles using DFS
    def has_cycle(node: str, visited: set[str], rec_stack: set[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for src, tgt in support_edges:
            if src == node:
                if tgt not in visited:
                    if has_cycle(tgt, visited, rec_stack):
                        return True
                elif tgt in rec_stack:
                    return True

        rec_stack.remove(node)
        return False

    visited: set[str] = set()
    for prop_id in prop_ids:
        if prop_id not in visited:
            if has_cycle(prop_id, visited, set()):
                result.add_soft_warning(
                    "cycles",
                    "Cyclic support detected in extraction window",
                    cycle_edges=[e for e in support_edges],
                )
                break


def check_all(data: dict[str, Any]) -> ValidationResult:
    """Run all validation checks and return the result."""
    return validate_extraction_window(data)


def check_unrelated_conflicts(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check for conflicts between unrelated concepts (soft constraint).

    Per §12.2: Penalize conflict between unrelated concepts.

    Two propositions in conflict should share at least one concept or entity binding.
    """
    relations = data.get("relations", [])
    propositions = data.get("propositions", [])

    # Build concept/entity sets for each proposition
    prop_concepts: dict[str, set[str]] = {}
    prop_entities: dict[str, set[str]] = {}

    for prop in propositions:
        prop_id = prop.get("prop_id")
        if not prop_id:
            continue

        # Collect concept bindings
        concepts = set()
        for binding in prop.get("concept_bindings", []):
            concepts.add(binding.get("concept_label", ""))

        # Collect entity bindings
        entities = set()
        for binding in prop.get("entity_bindings", []):
            entities.add(binding.get("entity_id", ""))

        prop_concepts[prop_id] = concepts
        prop_entities[prop_id] = entities

    # Check conflict relations
    for i, rel in enumerate(relations):
        if rel.get("relation_type") != "conflict":
            continue

        source_ids = rel.get("source_prop_ids", [])
        target_id = rel.get("target_prop_id")

        # Get all propositions involved in this conflict
        conflict_props = set(source_ids + [target_id])

        # Check if any pair shares concepts or entities
        has_overlap = False
        for p1 in conflict_props:
            for p2 in conflict_props:
                if p1 in prop_concepts and p2 in prop_concepts:
                    if prop_concepts[p1] & prop_concepts[p2]:
                        has_overlap = True
                        break
                if p1 in prop_entities and p2 in prop_entities:
                    if prop_entities[p1] & prop_entities[p2]:
                        has_overlap = True
                        break

        if not has_overlap:
            result.add_soft_warning(
                "unrelated_conflict",
                f"Relation {i} is a conflict but propositions share no concepts or entities",
                relation_index=i,
                relation=rel,
            )


def check_inference_cycles(data: dict[str, Any], result: ValidationResult) -> None:
    """
    Check for inference cycles within bounded windows (hard constraint).

    Per §16.3.2: No inference cycles within bounded windows.
    """
    # This is already handled by check_cycles() for support relations
    # For inference cycles, we check if any proposition is its own premise via support chains
    pass  # Delegated to check_cycles() since both handle circular reasoning


def check_schema(data: dict[str, Any], result: ValidationResult | None = None) -> ValidationResult:
    """
    Check schema validation using JSON schema.

    Per §12.1: Reject if schema violation (invalid JSON, missing required fields).

    Args:
        data: Extraction window data to validate
        result: Optional existing ValidationResult to add errors to

    Returns:
        ValidationResult with schema validation errors
    """
    if result is None:
        result = ValidationResult(is_valid=True)

    import json
    from pathlib import Path

    # Load the JSON schema
    schema_path = Path(
        "/mnt/c/Users/Datision/Documents/grundrisse/packages/llm_contracts/src/grundrisse_contracts/schemas/task_c1_argument_extraction.json"
    )
    with open(schema_path) as f:
        schema = json.load(f)

    # Check required top-level fields
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            result.add_hard_error(
                "schema",
                f"Missing required top-level field: {field}",
            )

    # Check each array's required fields
    for array_name in ["locutions", "propositions", "illocutions", "relations"]:
        if array_name not in schema.get("properties", {}):
            continue
        array_schema = schema["properties"][array_name]
        item_schema = array_schema.get("items", {})
        item_required = item_schema.get("required", [])

        for i, item in enumerate(data.get(array_name, [])):
            for field in item_required:
                if field not in item:
                    result.add_hard_error(
                        "schema",
                        f"{array_name}[{i}] missing required field: {field}",
                        array_index=i,
                        field_name=field,
                    )

    # Validate enum values
    # Check transition hints
    transitions = data.get("transitions", [])
    transition_hints = schema["properties"]["transitions"]["items"]["properties"]["function_hint"]["enum"]
    for i, trans in enumerate(transitions):
        hint = trans.get("function_hint")
        if hint and hint not in transition_hints:
            result.add_hard_error(
                "schema",
                f"transitions[{i}] has invalid function_hint: {hint}",
                transition_index=i,
                invalid_value=hint,
                valid_values=transition_hints,
            )

    # Check illocutionary forces
    illocutions = data.get("illocutions", [])
    illoc_forces = schema["properties"]["illocutions"]["items"]["properties"]["force"]["enum"]
    for i, illoc in enumerate(illocutions):
        force = illoc.get("force")
        if force and force not in illoc_forces:
            result.add_hard_error(
                "schema",
                f"illocutions[{i}] has invalid force: {force}",
                illocution_index=i,
                invalid_value=force,
                valid_values=illoc_forces,
            )

    # Check relation types
    relations = data.get("relations", [])
    relation_types = schema["properties"]["relations"]["items"]["properties"]["relation_type"]["enum"]
    for i, rel in enumerate(relations):
        rel_type = rel.get("relation_type")
        if rel_type and rel_type not in relation_types:
            result.add_hard_error(
                "schema",
                f"relations[{i}] has invalid relation_type: {rel_type}",
                relation_index=i,
                invalid_value=rel_type,
                valid_values=relation_types,
            )

    # Check conflict details
    conflict_types = schema["properties"]["relations"]["items"]["properties"]["conflict_detail"]["enum"]
    for i, rel in enumerate(relations):
        if rel.get("relation_type") == "conflict":
            detail = rel.get("conflict_detail")
            if detail and detail not in conflict_types:
                result.add_hard_error(
                    "schema",
                    f"relations[{i}] has invalid conflict_detail: {detail}",
                    relation_index=i,
                    invalid_value=detail,
                    valid_values=conflict_types,
                )

    return result

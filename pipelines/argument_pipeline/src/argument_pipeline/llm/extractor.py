"""Argument Extraction LLM Client.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.2 (Execution Model):

This module implements the LLM-based argument extraction agent that:
- Processes extraction windows with schema constraints
- Implements error-type-specific recovery (§13)
- Enforces hard constraints (grounding, evidence, AIF validity)
- Returns structured ExtractionWindow outputs

Uses Z.ai GLM client with retry logic and exponential backoff.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from nlp_pipeline.llm.client import LLMClient, LLMResponse
from pydantic import ValidationError

from argument_pipeline.settings import get_settings


# =============================================================================
# Error Types (per §13.1)
# =============================================================================

class ErrorType(str, Enum):
    """Error types for autonomous retries per §13.1."""
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    CONTEXT_EXHAUSTION = "CONTEXT_EXHAUSTION"
    OVERGENERATION = "OVERGENERATION"
    ENTITY_RESOLUTION_FAILURE = "ENTITY_RESOLUTION_FAILURE"
    RETRIEVAL_POISONING_RISK = "RETRIEVAL_POISONING_RISK"
    VALIDATION_CYCLE = "VALIDATION_CYCLE"


@dataclass
class ExtractionError:
    """Structured error object per §13.1."""
    error_type: ErrorType
    stage: str  # e.g., "proposition_extraction", "relation_classification"
    window_id: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    suggested_recovery: str = ""


@dataclass
class RetryPolicy:
    """Retry policy per §13.2."""
    max_retries: dict[ErrorType, int] = field(default_factory=lambda: {
        ErrorType.GROUNDING_FAILURE: 3,
        ErrorType.SCHEMA_VIOLATION: 3,
        ErrorType.CONTEXT_EXHAUSTION: 2,
        ErrorType.OVERGENERATION: 3,
        ErrorType.ENTITY_RESOLUTION_FAILURE: 1,
        ErrorType.RETRIEVAL_POISONING_RISK: 2,
        ErrorType.VALIDATION_CYCLE: 0,  # Fatal, requires manual review
    })
    base_backoff_seconds: int = 1


# =============================================================================
# Prompt Templates
# =============================================================================

_SYSTEM_PROMPT = """You are an argument extraction agent for Marxist philosophical texts.

Your task is to extract argumentative structures from text, following the AIF/IAT framework:
- L-nodes (Locutions): concrete text spans
- I-nodes (Propositions): abstract content
- Illocutions: what is done with the text (assert, deny, attribute, etc.)
- S-nodes (Relations): support, conflict, rephrase between propositions
- Transitions: discourse markers (however, therefore, etc.)

CRITICAL CONSTRAINTS:
1. Every proposition MUST cite at least one locution in surface_loc_ids (grounding is mandatory)
2. Every relation MUST cite evidence locutions (evidence_loc_ids with minItems=1)
3. Do NOT extract from retrieved_context - it is read-only for context only
4. Use the 10 illocutionary forces: assert, deny, question, define, distinguish, attribute, concede, ironic, hypothetical, prescriptive
5. Use the 4 transition hints: contrast, inference, concession, continuation

Return ONLY valid JSON that conforms to the provided schema.
"""

# Per §5.4: LOCAL WINDOW comes first, then RETRIEVED CONTEXT
_WINDOW_TEMPLATE = """--- LOCAL WINDOW (extractable) ---
The following paragraphs are the current extraction window. Extract all locutions,
propositions, illocutions, and relations from this text.

{paragraphs}
--- END LOCAL WINDOW ---

"""

_RETRIEVAL_CONTEXT_TEMPLATE = """--- RETRIEVED CONTEXT (read-only, non-extractible) ---
The following propositions were extracted from earlier parts of this text or related texts.
You may cite these as premises in relations, but DO NOT create new locutions from them.
DO NOT re-extract them as new propositions.

{retrieved_items}
--- END RETRIEVED CONTEXT ---
"""

_DISCOURSE_MARKERS_HINT = """
Detected discourse markers in this window:
{markers}

These markers signal likely argumentative transitions. Use them to identify relations.
"""


def _build_extraction_prompt(
    paragraphs: list[str],
    discourse_markers: list[dict] | None = None,
    retrieved_context: list[dict] | None = None,
) -> str:
    """Build the extraction prompt for a window.

    Per §5.4: Order is LOCAL WINDOW first, then RETRIEVED CONTEXT.
    """
    parts = [_SYSTEM_PROMPT]

    # Add discourse marker hints (before main text)
    if discourse_markers:
        marker_strs = [f"- {m.get('marker', '')} ({m.get('function_hint', '')}) at position {m.get('position', '')}"
                      for m in discourse_markers]
        parts.append(_DISCOURSE_MARKERS_HINT.format(markers="\n".join(marker_strs)))

    # Add main text (LOCAL WINDOW first per §5.4)
    para_text = "\n\n".join(f"[Paragraph {i+1}] {p}" for i, p in enumerate(paragraphs))
    parts.append(_WINDOW_TEMPLATE.format(paragraphs=para_text))

    # Add retrieved context after main text (per §5.4)
    if retrieved_context:
        items = []
        for i, prop in enumerate(retrieved_context, 1):
            # Support both source_doc_id and doc_id for compatibility
            source = prop.get('source_doc_id') or prop.get('doc_id', 'unknown')
            items.append(f"[{i}] {prop.get('prop_id', '')}: \"{prop.get('text_summary', '')}\" "
                       f"(from {source})")
        parts.append(_RETRIEVAL_CONTEXT_TEMPLATE.format(retrieved_items="\n".join(items)))

    return "\n\n".join(parts)


# =============================================================================
# Argument Extractor
# =============================================================================

@dataclass
class ExtractionResult:
    """Result of argument extraction."""
    success: bool
    data: dict[str, Any] | None = None
    error: ExtractionError | None = None
    retry_count: int = 0
    elapsed_seconds: float = 0.0


class ArgumentExtractor:
    """
    LLM-based argument extraction agent.

    Per §16.2.1: The agent reasons about schemas, constraints, and graph structure,
    not about Marxism itself.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        schema_path: Path | None = None,
        retry_policy: RetryPolicy | None = None,
    ):
        """
        Initialize the argument extractor.

        Args:
            llm_client: LLM client (uses Z.ai GLM if None)
            schema_path: Path to JSON schema (uses task_c1_argument_extraction.json if None)
            retry_policy: Retry policy per §13.2
        """
        self.llm_client = llm_client
        self.retry_policy = retry_policy or RetryPolicy()
        self.settings = get_settings()

        # Load schema
        if schema_path is None:
            schema_path = Path(
                "/mnt/c/Users/Datision/Documents/grundrisse/packages/llm_contracts/src/grundrisse_contracts/schemas/task_c1_argument_extraction.json"
            )
        with open(schema_path) as f:
            self.schema = json.load(f)

    def extract_window(
        self,
        window_id: str,
        paragraphs: list[str],
        doc_id: str,
        discourse_markers: list[dict] | None = None,
        retrieved_context: list[dict] | None = None,
    ) -> ExtractionResult:
        """
        Extract arguments from a single window.

        Args:
            window_id: Unique window identifier
            paragraphs: Paragraph texts in the window
            doc_id: Document identifier
            discourse_markers: Detected discourse markers
            retrieved_context: Previously extracted propositions (read-only)

        Returns:
            ExtractionResult with data or error
        """
        started = time.time()
        prompt = _build_extraction_prompt(paragraphs, discourse_markers, retrieved_context)

        # Attempt extraction with retries
        last_error: ExtractionError | None = None
        retry_count = 0

        while retry_count <= self._max_retries_for_stage("extraction"):
            try:
                response = self._call_llm(prompt)
                elapsed = time.time() - started

                # Validate response against schema
                validated = self._validate_response(response, window_id, doc_id, paragraphs)

                if validated.success:
                    validated.elapsed_seconds = elapsed
                    return validated
                else:
                    last_error = validated.error
                    # Check if we should retry
                    if retry_count >= self._max_retries_for_error(validated.error.error_type):
                        break
                    retry_count += 1
                    self._backoff(retry_count)

            except Exception as e:
                last_error = ExtractionError(
                    error_type=ErrorType.SCHEMA_VIOLATION,
                    stage="llm_call",
                    window_id=window_id,
                    message=str(e),
                    retry_count=retry_count,
                )
                if retry_count >= self.retry_policy.max_retries.get(ErrorType.SCHEMA_VIOLATION, 3):
                    break
                retry_count += 1
                self._backoff(retry_count)

        # All retries exhausted
        return ExtractionResult(
            success=False,
            error=last_error,
            retry_count=retry_count,
            elapsed_seconds=time.time() - started,
        )

    def _call_llm(self, prompt: str) -> LLMResponse:
        """Call the LLM with the extraction prompt."""
        if self.llm_client is None:
            # Lazy import to avoid circular dependency
            from nlp_pipeline.llm.zai_glm import ZaiGlmClient
            settings = get_settings()
            self.llm_client = ZaiGlmClient(  # type: ignore
                api_key=settings.zai_api_key or "",
                base_url=settings.zai_base_url,
                model=settings.zai_model,
                timeout_s=settings.zai_timeout_s,
            )

        return self.llm_client.complete_json(prompt=prompt, schema=self.schema)

    def _validate_response(
        self,
        response: LLMResponse,
        window_id: str,
        doc_id: str,
        paragraphs: list[str],
    ) -> ExtractionResult:
        """
        Validate LLM response against hard constraints.

        Per §12.1: Reject if span grounding, AIF validity, or evidence missing.
        """
        if response.json is None:
            return ExtractionResult(
                success=False,
                error=ExtractionError(
                    error_type=ErrorType.SCHEMA_VIOLATION,
                    stage="json_parse",
                    window_id=window_id,
                    message="Failed to parse JSON from LLM response",
                    details={"raw_text": response.raw_text[:500]},
                ),
            )

        data = response.json

        # Check 1: All required fields present
        for field in ["locutions", "propositions", "illocutions", "relations"]:
            if field not in data:
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.SCHEMA_VIOLATION,
                        stage="required_fields",
                        window_id=window_id,
                        message=f"Missing required field: {field}",
                    ),
                )

        # Check 2: Grounding - all propositions must cite locutions
        for i, prop in enumerate(data.get("propositions", [])):
            surface_loc_ids = prop.get("surface_loc_ids", [])
            if not surface_loc_ids or not isinstance(surface_loc_ids, list):
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.GROUNDING_FAILURE,
                        stage="proposition_grounding",
                        window_id=window_id,
                        message=f"Proposition {i} missing surface_loc_ids",
                        details={"proposition": prop},
                    ),
                )

        # Check 3: Evidence - all relations must cite evidence
        for i, rel in enumerate(data.get("relations", [])):
            evidence_loc_ids = rel.get("evidence_loc_ids", [])
            if not evidence_loc_ids or not isinstance(evidence_loc_ids, list):
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.GROUNDING_FAILURE,
                        stage="relation_evidence",
                        window_id=window_id,
                        message=f"Relation {i} missing evidence_loc_ids",
                        details={"relation": rel},
                    ),
                )

        # Check 4: Illocutions must link to existing locutions and propositions
        loc_ids = {loc.get("loc_id") for loc in data.get("locutions", [])}
        prop_ids = {prop.get("prop_id") for prop in data.get("propositions", [])}

        for i, illoc in enumerate(data.get("illocutions", [])):
            source_id = illoc.get("source_loc_id")
            target_id = illoc.get("target_prop_id")
            if source_id not in loc_ids:
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.GROUNDING_FAILURE,
                        stage="illocution_source",
                        window_id=window_id,
                        message=f"Illocution {i} references non-existent locution: {source_id}",
                    ),
                )
            if target_id not in prop_ids:
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.GROUNDING_FAILURE,
                        stage="illocution_target",
                        window_id=window_id,
                        message=f"Illocution {i} references non-existent proposition: {target_id}",
                    ),
                )

        # Check 5: Relations must link to existing propositions
        for i, rel in enumerate(data.get("relations", [])):
            source_ids = rel.get("source_prop_ids", [])
            target_id = rel.get("target_prop_id")
            for sid in source_ids:
                if sid not in prop_ids:
                    return ExtractionResult(
                        success=False,
                        error=ExtractionError(
                            error_type=ErrorType.GROUNDING_FAILURE,
                            stage="relation_source",
                            window_id=window_id,
                            message=f"Relation {i} references non-existent proposition: {sid}",
                        ),
                    )
            if target_id not in prop_ids:
                return ExtractionResult(
                    success=False,
                    error=ExtractionError(
                        error_type=ErrorType.GROUNDING_FAILURE,
                        stage="relation_target",
                        window_id=window_id,
                        message=f"Relation {i} references non-existent proposition: {target_id}",
                    ),
                )

        # Check 6: Overgeneration (soft constraint)
        num_props = len(data.get("propositions", []))
        num_paras = len(paragraphs)
        if num_props > num_paras * 5:  # More than 5 propositions per paragraph is suspicious
            return ExtractionResult(
                success=False,
                error=ExtractionError(
                    error_type=ErrorType.OVERGENERATION,
                    stage="overgeneration",
                    window_id=window_id,
                    message=f"Too many propositions: {num_props} for {num_paras} paragraphs",
                    details={"proposition_count": num_props, "paragraph_count": num_paras},
                ),
            )

        # All checks passed
        return ExtractionResult(
            success=True,
            data=data,
        )

    def _max_retries_for_error(self, error_type: ErrorType) -> int:
        """Get max retries for a specific error type."""
        return self.retry_policy.max_retries.get(error_type, 3)

    def _max_retries_for_stage(self, stage: str) -> int:
        """Get max retries for a pipeline stage."""
        return 3  # Default

    def _backoff(self, retry_count: int) -> None:
        """Exponential backoff: 2^N seconds."""
        backoff = self.retry_policy.base_backoff_seconds * (2 ** retry_count)
        time.sleep(backoff)


# =============================================================================
# Convenience Functions
# =============================================================================

def extract_from_window(
    window_id: str,
    paragraphs: list[str],
    doc_id: str,
    discourse_markers: list[dict] | None = None,
    retrieved_context: list[dict] | None = None,
    llm_client: LLMClient | None = None,
) -> ExtractionResult:
    """
    Convenience function to extract arguments from a window.

    Args:
        window_id: Unique window identifier
        paragraphs: Paragraph texts in the window
        doc_id: Document identifier
        discourse_markers: Detected discourse markers
        retrieved_context: Previously extracted propositions (read-only)
        llm_client: Optional LLM client

    Returns:
        ExtractionResult with data or error
    """
    extractor = ArgumentExtractor(llm_client=llm_client)
    return extractor.extract_window(
        window_id=window_id,
        paragraphs=paragraphs,
        doc_id=doc_id,
        discourse_markers=discourse_markers,
        retrieved_context=retrieved_context,
    )

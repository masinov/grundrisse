"""Argument Extraction Pipeline Orchestrator.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.2 (Execution Model):

This orchestrator coordinates the end-to-end argument extraction pipeline:
- Stage 4: Windowing and retrieval setup
- Stage 5: LLM-based argument extraction
- Stage 6: Validation and stability filtering
- Stage 7: Vector indexing for retrieval

The orchestrator is designed to run under a persistent autonomous agent,
processing documents through idempotent, restartable stages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from argument_pipeline.llm.extractor import (
    ArgumentExtractor,
    ErrorType,
    ExtractionError,
    ExtractionResult,
    RetryPolicy,
)
from argument_pipeline.settings import get_settings
from argument_pipeline.validation.validators import ValidationResult, validate_extraction_window
from grundrisse_argument.windowing.builder import WindowBuilder, WindowBuilderConfig

# Phase 7: Vector and retrieval
from grundrisse_argument.retrieval import (
    RetrievalOrchestrator,
    RetrievalConfig,
    RetrievedContext,
)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ExtractionConfig:
    """Configuration for the argument extraction pipeline."""

    # Windowing configuration (§5.1)
    window_min_paragraphs: int = 2
    window_max_paragraphs: int = 6
    window_overlap: int = 1
    prefer_break_at_transitions: bool = True

    # Retrieval configuration (§5.2, §16.3.3)
    retrieval_enabled: bool = True
    retrieval_top_k: int = 5
    retrieval_threshold: float = 0.7
    retrieval_max_contexts: int = 3
    enable_mandatory_triggers: bool = True  # §5.3

    # Validation configuration (§12)
    max_retries: int = 3
    stability_threshold: float = 0.7

    # Indexing configuration (Phase 7)
    index_after_extraction: bool = True

    # Progress reporting
    progress_every_windows: int = 10
    commit_every_windows: int = 50


@dataclass
class WindowResult:
    """Result of processing a single window."""
    window_id: str
    success: bool
    data: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    error: ExtractionError | None = None
    retry_count: int = 0
    elapsed_seconds: float = 0.0
    retrieved_context: RetrievedContext | None = None  # Phase 7


@dataclass
class OrchestratorResult:
    """Result of the extraction pipeline."""
    success: bool
    total_windows: int = 0
    successful_windows: int = 0
    failed_windows: int = 0
    total_retries: int = 0
    total_elapsed_seconds: float = 0.0
    window_results: list[WindowResult] = field(default_factory=list)
    errors: list[ExtractionError] = field(default_factory=list)


# =============================================================================
# Orchestrator
# =============================================================================

class ArgumentExtractionOrchestrator:
    """
    Coordinates the argument extraction pipeline.

    Per §16.2.1: The agent reasons about schemas, constraints, and graph structure.
    """

    def __init__(
        self,
        config: ExtractionConfig | None = None,
        extractor: ArgumentExtractor | None = None,
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            config: Extraction configuration
            extractor: LLM-based argument extractor
            retrieval_orchestrator: Optional retrieval orchestrator for Phase 7
        """
        self.config = config or ExtractionConfig()
        self.settings = get_settings()
        self.extractor = extractor or ArgumentExtractor()
        self.retrieval_orchestrator = retrieval_orchestrator

        # Initialize window builder
        self.window_builder = WindowBuilder(WindowBuilderConfig(
            min_paragraphs=self.config.window_min_paragraphs,
            max_paragraphs=self.config.window_max_paragraphs,
            overlap=self.config.window_overlap,
            prefer_break_at_transitions=self.config.prefer_break_at_transitions,
        ))

    def process_document(
        self,
        edition_id: uuid.UUID,
        doc_id: str,
        session: Session,
    ) -> OrchestratorResult:
        """
        Process a document through the complete extraction pipeline.

        Args:
            edition_id: Edition UUID
            doc_id: Document identifier
            session: Database session

        Returns:
            OrchestratorResult with all window results
        """
        from grundrisse_core.db.models import Paragraph

        started = datetime.utcnow()

        # Query paragraphs in order
        paragraphs = (
            session.query(Paragraph)
            .filter(Paragraph.edition_id == edition_id)
            .order_by(Paragraph.order_index)
            .all()
        )

        if not paragraphs:
            return OrchestratorResult(
                success=True,
                total_windows=0,
                total_elapsed_seconds=(datetime.utcnow() - started).total_seconds(),
            )

        # Build windows
        windows = self.window_builder.build_windows(
            paragraphs=paragraphs,
            edition_id=edition_id,
            doc_id=doc_id,
        )

        result = OrchestratorResult(
            success=True,
            total_windows=len(windows),
            total_elapsed_seconds=0,
        )

        # Process each window
        for i, window in enumerate(windows):
            window_result = self._process_window(
                window=window,
                doc_id=doc_id,
                session=session,
            )
            result.window_results.append(window_result)
            result.total_retries += window_result.retry_count

            if window_result.success:
                result.successful_windows += 1
            else:
                result.failed_windows += 1
                if window_result.error:
                    result.errors.append(window_result.error)

            # Progress reporting
            if (i + 1) % self.config.progress_every_windows == 0:
                print(f"Processed {i + 1}/{len(windows)} windows "
                      f"(success: {result.successful_windows}, failed: {result.failed_windows})")

            # Commit periodically
            if (i + 1) % self.config.commit_every_windows == 0:
                session.commit()

        result.total_elapsed_seconds = (datetime.utcnow() - started).total_seconds()
        result.success = result.failed_windows == 0

        return result

    def _process_window(
        self,
        window: Any,  # ExtractionWindowInput from windowing module
        doc_id: str,
        session: Session,
    ) -> WindowResult:
        """Process a single window through extraction and validation."""
        window_id = window.window_id
        started = datetime.utcnow()

        # Phase 7: Retrieve context if enabled
        retrieved_context: RetrievedContext | None = None
        if self.retrieval_orchestrator and self.config.retrieval_enabled:
            window_text = " ".join(window.texts)
            retrieved_context = self.retrieval_orchestrator.retrieve_for_window(
                window_text=window_text,
                window_concepts=None,  # TODO: Extract concepts from window
                doc_id=doc_id,
                exclude_prop_ids=None,  # TODO: Track processed prop_ids
            )

        # Build retrieved context for LLM (per §5.4 format)
        retrieved_for_llm = []
        if retrieved_context and retrieved_context.propositions:
            retrieved_for_llm = [
                {
                    "prop_id": p.prop_id,
                    "text_summary": p.text_summary,
                    "extractable": False,  # Per §5.4: read-only constraint
                }
                for p in retrieved_context.propositions
            ]

        # Extract using LLM
        extraction_result = self.extractor.extract_window(
            window_id=window_id,
            paragraphs=window.texts,
            doc_id=doc_id,
            discourse_markers=[
                {
                    "marker": t["marker"],
                    "function_hint": t["function_hint"],  # Aligned with Appendix A
                    "position": t["position"],
                }
                for t in window.transitions
            ],
            retrieved_context=retrieved_for_llm,
        )

        elapsed = (datetime.utcnow() - started).total_seconds()

        if not extraction_result.success:
            return WindowResult(
                window_id=window_id,
                success=False,
                error=extraction_result.error,
                retry_count=extraction_result.retry_count,
                elapsed_seconds=elapsed,
                retrieved_context=retrieved_context,
            )

        # Validate extraction
        validation = validate_extraction_window(extraction_result.data)

        if validation.has_hard_errors:
            return WindowResult(
                window_id=window_id,
                success=False,
                error=ExtractionError(
                    error_type=ErrorType.SCHEMA_VIOLATION,
                    stage="validation",
                    window_id=window_id,
                    message="Validation failed with hard errors",
                    details={"errors": [e.message for e in validation.hard_errors]},
                ),
                validation=validation,
                elapsed_seconds=elapsed,
                retrieved_context=retrieved_context,
            )

        # Phase 7: Index propositions for retrieval after successful extraction
        if self.retrieval_orchestrator and self.config.index_after_extraction:
            self._index_propositions(
                data=extraction_result.data,
                doc_id=doc_id,
            )

        # Success - return result with warnings if any
        return WindowResult(
            window_id=window_id,
            success=True,
            data=extraction_result.data,
            validation=validation,
            retry_count=extraction_result.retry_count,
            elapsed_seconds=elapsed,
            retrieved_context=retrieved_context,
        )

    def _index_propositions(self, data: dict[str, Any], doc_id: str) -> None:
        """
        Index extracted propositions for retrieval (Phase 7).

        Called after successful extraction to make propositions available
        for retrieval in subsequent windows.
        """
        propositions_to_index = []

        for prop in data.get("propositions", []):
            prop_id = prop.get("prop_id")
            if not prop_id:
                continue

            # Extract concept labels
            concept_labels = [
                binding.get("concept_label", "")
                for binding in prop.get("concept_bindings", [])
            ]

            # Extract entity IDs
            entity_ids = [
                binding.get("entity_id", "")
                for binding in prop.get("entity_bindings", [])
            ]

            propositions_to_index.append({
                "prop_id": prop_id,
                "text_summary": prop.get("text_summary", ""),
                "concept_labels": concept_labels,
                "entity_ids": entity_ids,
                "doc_id": doc_id,
                "temporal_scope": prop.get("temporal_scope"),
                "is_implicit": prop.get("is_implicit_reconstruction", False),
            })

        # Batch index all propositions
        if propositions_to_index:
            self.retrieval_orchestrator.index_propositions_batch(propositions_to_index)


# =============================================================================
# Convenience Functions
# =============================================================================

def run_extraction_pipeline(
    edition_id: uuid.UUID,
    doc_id: str,
    session: Session,
    config: ExtractionConfig | None = None,
) -> OrchestratorResult:
    """
    Convenience function to run the complete extraction pipeline.

    Args:
        edition_id: Edition UUID to process
        doc_id: Document identifier
        session: Database session
        config: Optional extraction configuration

    Returns:
        OrchestratorResult with all window results
    """
    orchestrator = ArgumentExtractionOrchestrator(config=config)
    return orchestrator.process_document(
        edition_id=edition_id,
        doc_id=doc_id,
        session=session,
    )

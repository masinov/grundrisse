"""Pipeline stages.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.4 (Pipeline Stages):
- Stage 1: Corpus ingestion and structural parsing (reuse existing)
- Stage 2: Entity normalization (TODO)
- Stage 3: Normalization with reversibility (reuse existing)
- Stage 4: Windowing and retrieval setup (implemented)
- Stage 5: Argument extraction (implemented)
- Stage 6: Validation and stability filtering (implemented)
- Stage 7: Vector indexing and retrieval (implemented)
- Stage 8-11: Higher-level analysis (TODO)
"""

from argument_pipeline.stages.orchestrator import (
    ArgumentExtractionOrchestrator,
    ExtractionConfig,
    OrchestratorResult,
    WindowResult,
    run_extraction_pipeline,
)

__all__ = [
    "ArgumentExtractionOrchestrator",
    "ExtractionConfig",
    "OrchestratorResult",
    "WindowResult",
    "run_extraction_pipeline",
]

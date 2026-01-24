"""
Grundrisse Argument Extraction Package

Core AIF/IAT data models for unsupervised argument and dialectical motion extraction.
"""

__version__ = "0.1.0"

from grundrisse_argument.models.locution import Locution
from grundrisse_argument.models.proposition import Proposition, ConceptBinding, EntityBinding
from grundrisse_argument.models.illocution import IllocutionaryEdge, IllocutionType
from grundrisse_argument.models.relation import ArgumentRelation, RelationType, ConflictType
from grundrisse_argument.models.transition import Transition, TransitionHint
from grundrisse_argument.models.extraction import ExtractionWindow
from grundrisse_argument.errors.types import ErrorType, ExtractionError, RetryPolicy

# Vector and retrieval (Phase 7)
from grundrisse_argument.vector import (
    QdrantSettings,
    QdrantClient,
    PropositionVector,
    ConceptVector,
    EntityVector,
    RetrievedProposition,
    RetrievalResult,
)
from grundrisse_argument.embeddings import (
    EmbeddingSettings,
    EmbeddingEncoder,
    create_embedding_encoder,
)
from grundrisse_argument.retrieval import (
    RetrievalConfig,
    RetrievedContext,
    RetrievalOrchestrator,
    CONCLUSION_MARKERS,
    EVALUATIVE_MARKERS,
    DEFINITIONAL_FORCE_TAGS,
)

# Dialectical structure (Stage 8)
from grundrisse_argument.dialectical import (
    MotionPatternType,
    ContradictionType,
    PropositionCluster,
    ClusterRelation,
    ContradictionCluster,
    DialecticalNode,
    DialecticalEdge,
    DialecticalTree,
    MotionHypothesis,
    DocumentDialecticalStructure,
)
from grundrisse_argument.dialectical_builder import (
    DialecticalBuilderConfig,
    DialecticalStructureBuilder,
    build_dialectical_structure,
)

__all__ = [
    # Models
    "Locution",
    "Proposition",
    "ConceptBinding",
    "EntityBinding",
    "IllocutionaryEdge",
    "IllocutionType",
    "ArgumentRelation",
    "RelationType",
    "ConflictType",
    "Transition",
    "TransitionHint",
    "ExtractionWindow",
    # Errors
    "ErrorType",
    "ExtractionError",
    "RetryPolicy",
    # Vector (Phase 7)
    "QdrantSettings",
    "QdrantClient",
    "PropositionVector",
    "ConceptVector",
    "EntityVector",
    "RetrievedProposition",
    "RetrievalResult",
    # Embeddings (Phase 7)
    "EmbeddingSettings",
    "EmbeddingEncoder",
    "create_embedding_encoder",
    # Retrieval (Phase 7)
    "RetrievalConfig",
    "RetrievedContext",
    "RetrievalOrchestrator",
    "CONCLUSION_MARKERS",
    "EVALUATIVE_MARKERS",
    "DEFINITIONAL_FORCE_TAGS",
    # Dialectical (Stage 8)
    "MotionPatternType",
    "ContradictionType",
    "PropositionCluster",
    "ClusterRelation",
    "ContradictionCluster",
    "DialecticalNode",
    "DialecticalEdge",
    "DialecticalTree",
    "MotionHypothesis",
    "DocumentDialecticalStructure",
    "DialecticalBuilderConfig",
    "DialecticalStructureBuilder",
    "build_dialectical_structure",
]

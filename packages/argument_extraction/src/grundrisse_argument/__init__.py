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
]

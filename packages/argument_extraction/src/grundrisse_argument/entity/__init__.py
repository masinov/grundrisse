"""
Entity normalization for attribution stability.

Canonicalizes named entities (persons, schools, positions) to prevent
fragmentation of attributed positions across windows and documents.
"""

from typing import Optional, List, Dict
from pydantic import BaseModel

from grundrisse_argument.models.proposition import EntityBinding, EntityBinding as EntityBindingModel


class EntityCatalog(BaseModel):
    """
    Global entity catalog for canonicalization.

    Maps surface forms to stable entity_ids.
    """

    entities: Dict[str, "Entity"] = Field(default_factory=dict)

    # TODO: Implement entity catalog with persistence
    # - add_entity()
    # - resolve_surface_form()
    # - merge_entities()
    # - export_catalog()


class Entity(BaseModel):
    """A canonical entity in the catalog."""

    entity_id: str
    canonical_name: str
    entity_type: str  # "person", "school", "position"
    surface_forms: List[str] = []
    context_references: List[str] = []  # doc_ids where this entity appears


class EntityNormalizer:
    """
    Entity normalization using spaCy.

    1. Canonicalize named entities to stable entity_ids
    2. Distinguish entity types (person, school, position)
    3. Create entity bindings for propositions
    4. Stabilize attribution across windows
    """

    def __init__(self, model_name: str = "en_core_web_trf"):
        self.model_name = model_name
        self._nlp = None

    def load_model(self):
        """Load spaCy model."""
        try:
            import spacy

            self._nlp = spacy.load(self.model_name)
        except OSError:
            raise ImportError(
                f"spaCy model '{self.model_name}' not found. "
                f"Install with: python -m spacy download {self.model_name}"
            )

    def normalize_entities(
        self, text: str, doc_id: str, catalog: EntityCatalog
    ) -> List[EntityBindingModel]:
        """
        Extract and normalize entities from text.

        Returns EntityBindings for the proposition.
        """
        # TODO: Implement entity normalization
        # - Run spaCy NER
        # - Match against catalog
        # - Create new entities for unknown surface forms
        # - Return EntityBindings
        return []

    # TODO: Implement disambiguation logic
    # - resolve_by_context()
    # - merge_similar_entities()

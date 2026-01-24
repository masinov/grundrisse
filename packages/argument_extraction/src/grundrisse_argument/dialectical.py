"""
Dialectical structure analysis per Stage 8.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §8, §11:

Stage 8: Per-document dialectical structure
- Retrieve all propositions within the document
- Build internal support/conflict networks
- Identify local contradiction clusters
- Generate internal dialectical trees

§11: Dialectical motion derivation (computed, not extracted)
- Contradiction candidates: two clusters with persistent conflict
- Motion patterns: graph-structural triggers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from uuid import UUID


# =============================================================================
# Enums
# =============================================================================

class MotionPatternType(str, Enum):
    """Types of dialectical motion patterns per §11.2."""
    CONFLICT_TO_DEFINITION = "conflict_to_definition"  # Conflict → definitional re-articulation
    ABSTRACT_TO_CONCRETE = "abstract_to_concrete"      # Abstract opposition → concrete mechanism
    FAILURE_TO_STRUCTURE = "failure_to_structure"      # Repeated failure → new structural determination


class ContradictionType(str, Enum):
    """Types of contradiction clusters."""
    DIRECT = "direct"           # Direct negation between propositions
    CONCEPT_DRIFT = "concept_drift"  # Same concept, different meanings over time
    STRUCTURAL = "structural"   # Incompatible structural positions


# =============================================================================
# Proposition Clusters
# =============================================================================

@dataclass
class PropositionCluster:
    """
    A cluster of related propositions.

    Formed by equivalence (rephrase) relations and shared concept bindings.
    """
    cluster_id: str
    prop_ids: list[str]
    canonical_summary: str | None = None
    concept_labels: list[str] = field(default_factory=list)
    temporal_scope: str | None = None
    confidence: float = 1.0


@dataclass
class ClusterRelation:
    """Relation between proposition clusters."""
    source_cluster_id: str
    target_cluster_id: str
    relation_type: str  # support, conflict, rephrase
    evidence_prop_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0


# =============================================================================
# Contradiction Clusters
# =============================================================================

@dataclass
class ContradictionCluster:
    """
    A set of proposition clusters in persistent conflict.

    Per §11.1: A contradiction candidate consists of:
    - Two proposition clusters
    - Persistent conflict edges
    - Shared concept bindings
    - Comparable temporal scope
    """
    contradiction_id: str
    cluster_a_id: str  # First opposing cluster
    cluster_b_id: str  # Second opposing cluster
    contradiction_type: ContradictionType
    shared_concepts: list[str] = field(default_factory=list)
    conflict_edges: list[str] = field(default_factory=list)  # Relation IDs
    temporal_compatible: bool = True
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Dialectical Trees
# =============================================================================

@dataclass
class DialecticalNode:
    """A node in a dialectical tree."""
    node_id: str
    prop_id: str | None = None  # For proposition nodes
    cluster_id: str | None = None  # For cluster-level nodes
    node_type: str = "proposition"  # proposition, cluster, conflict


@dataclass
class DialecticalEdge:
    """An edge in a dialectical tree."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: str  # support, conflict, rephrase, implies
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class DialecticalTree:
    """
    A dialectical tree for a document.

    Represents the internal argumentative structure:
    - Support networks (premise → conclusion)
    - Conflict networks (opposing positions)
    - Equivalence networks (paraphrases, abstractions)

    Built from extracted propositions and relations.
    """
    tree_id: str  # doc_id
    nodes: list[DialecticalNode] = field(default_factory=list)
    edges: list[DialecticalEdge] = field(default_factory=list)
    contradictions: list[ContradictionCluster] = field(default_factory=list)
    clusters: list[PropositionCluster] = field(default_factory=list)

    def get_support_network(self) -> list[DialecticalEdge]:
        """Get all support edges in the tree."""
        return [e for e in self.edges if e.edge_type == "support"]

    def get_conflict_network(self) -> list[DialecticalEdge]:
        """Get all conflict edges in the tree."""
        return [e for e in self.edges if e.edge_type == "conflict"]

    def get_equivalence_network(self) -> list[DialecticalEdge]:
        """Get all equivalence edges in the tree."""
        return [e for e in self.edges if e.edge_type == "rephrase"]


# =============================================================================
# Motion Hypotheses (§11.2)
# =============================================================================

@dataclass
class MotionHypothesis:
    """
    A hypothesis about dialectical motion.

    Per §11.2: Triggered ONLY by graph-structural patterns.
    """
    hypothesis_id: str
    pattern_type: MotionPatternType
    trigger_node_ids: list[str]  # Specific nodes forming the pattern
    trigger_edge_ids: list[str]  # Specific edges forming the pattern
    description: str
    supporting_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def is_valid(self) -> bool:
        """Check if hypothesis has required structural triggers."""
        return (
            len(self.trigger_node_ids) > 0 and
            len(self.trigger_edge_ids) > 0
        )


# =============================================================================
# Document Dialectical Structure
# =============================================================================

@dataclass
class DocumentDialecticalStructure:
    """
    Complete dialectical analysis for a single document.

    Per Stage 8:
    - All propositions within the document
    - Internal support/conflict networks
    - Local contradiction clusters
    - Internal dialectical tree
    """
    doc_id: str
    propositions: list[dict[str, Any]]  # Raw proposition data
    relations: list[dict[str, Any]]     # Raw relation data
    illocutions: list[dict[str, Any]]   # Raw illocution data
    tree: DialecticalTree
    motion_hypotheses: list[MotionHypothesis] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def get_proposition_count(self) -> int:
        """Get number of propositions in document."""
        return len(self.propositions)

    def get_relation_count(self) -> int:
        """Get number of relations in document."""
        return len(self.relations)

    def get_contradiction_count(self) -> int:
        """Get number of contradiction clusters."""
        return len(self.tree.contradictions)

    def get_cluster_count(self) -> int:
        """Get number of proposition clusters."""
        return len(self.tree.clusters)


__all__ = [
    # Enums
    "MotionPatternType",
    "ContradictionType",
    # Clusters
    "PropositionCluster",
    "ClusterRelation",
    # Contradictions
    "ContradictionCluster",
    # Trees
    "DialecticalNode",
    "DialecticalEdge",
    "DialecticalTree",
    # Motion
    "MotionHypothesis",
    # Document structure
    "DocumentDialecticalStructure",
]

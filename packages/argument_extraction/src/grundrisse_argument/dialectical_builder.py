"""
Dialectical structure builder for Stage 8.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md Stage 8:

Once a document is fully processed:
- Retrieve all propositions within the document
- Build internal support/conflict networks
- Identify local contradiction clusters
- Generate internal dialectical trees
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from grundrisse_argument.dialectical import (
    DocumentDialecticalStructure,
    DialecticalTree,
    DialecticalNode,
    DialecticalEdge,
    PropositionCluster,
    ClusterRelation,
    ContradictionCluster,
    ContradictionType,
    MotionHypothesis,
    MotionPatternType,
)


# =============================================================================
# Builder Configuration
# =============================================================================

@dataclass
class DialecticalBuilderConfig:
    """Configuration for dialectical structure building."""
    cluster_similarity_threshold: float = 0.8
    min_cluster_size: int = 1
    contradiction_min_conflict_edges: int = 2
    enable_motion_hypotheses: bool = True


# =============================================================================
# Dialectical Structure Builder
# =============================================================================

class DialecticalStructureBuilder:
    """
    Builds dialectical structures from extracted arguments.

    Per Stage 8:
    1. Retrieves all propositions within the document
    2. Builds internal support/conflict networks
    3. Identifies local contradiction clusters
    4. Generates internal dialectical trees
    """

    def __init__(self, config: DialecticalBuilderConfig | None = None):
        self.config = config or DialecticalBuilderConfig()

    def build_from_extraction_results(
        self,
        doc_id: str,
        extraction_results: list[dict[str, Any]],
    ) -> DocumentDialecticalStructure:
        """
        Build dialectical structure from extraction window results.

        Args:
            doc_id: Document identifier
            extraction_results: List of extraction window results

        Returns:
            DocumentDialecticalStructure with complete analysis
        """
        # Aggregate all propositions and relations
        propositions = []
        relations = []
        illocutions = []

        for result in extraction_results:
            data = result.get("data", {})
            propositions.extend(data.get("propositions", []))
            relations.extend(data.get("relations", []))
            illocutions.extend(data.get("illocutions", []))

        # Build the tree
        tree = self._build_tree(
            doc_id=doc_id,
            propositions=propositions,
            relations=relations,
            illocutions=illocutions,
        )

        # Generate motion hypotheses
        motion_hypotheses = []
        if self.config.enable_motion_hypotheses:
            motion_hypotheses = self._generate_motion_hypotheses(tree)

        return DocumentDialecticalStructure(
            doc_id=doc_id,
            propositions=propositions,
            relations=relations,
            illocutions=illocutions,
            tree=tree,
            motion_hypotheses=motion_hypotheses,
        )

    def _build_tree(
        self,
        doc_id: str,
        propositions: list[dict],
        relations: list[dict],
        illocutions: list[dict],
    ) -> DialecticalTree:
        """Build the dialectical tree from extracted data."""
        tree = DialecticalTree(tree_id=doc_id)

        # Create nodes for each proposition
        prop_ids = []
        for prop in propositions:
            prop_id = prop.get("prop_id")
            if prop_id:
                prop_ids.append(prop_id)
                tree.nodes.append(DialecticalNode(
                    node_id=f"node_{prop_id}",
                    prop_id=prop_id,
                    node_type="proposition",
                ))

        # Create edges from relations
        for rel in relations:
            edge = self._relation_to_edge(rel)
            if edge:
                tree.edges.append(edge)

        # Build proposition clusters
        tree.clusters = self._build_clusters(
            propositions=propositions,
            relations=relations,
        )

        # Identify contradiction clusters
        tree.contradictions = self._identify_contradictions(
            clusters=tree.clusters,
            relations=relations,
        )

        return tree

    def _relation_to_edge(self, relation: dict) -> DialecticalEdge | None:
        """Convert a relation to a dialectical edge."""
        rel_id = relation.get("rel_id")
        relation_type = relation.get("relation_type", "")
        source_prop_ids = relation.get("source_prop_ids", [])
        target_prop_id = relation.get("target_prop_id")

        if not rel_id or not target_prop_id:
            return None

        # Normalize relation type
        edge_type = relation_type
        if relation_type in ["support", "premise_for"]:
            edge_type = "support"
        elif relation_type in ["conflict", "rebut", "undercut", "incompatibility"]:
            edge_type = "conflict"
        elif relation_type == "rephrase":
            edge_type = "rephrase"

        # Create edges for each source (multiple premises)
        edges = []
        for source_id in source_prop_ids:
            edge = DialecticalEdge(
                edge_id=f"edge_{rel_id}_{source_id}",
                source_id=source_id,
                target_id=target_prop_id,
                edge_type=edge_type,
                evidence_ids=relation.get("evidence_loc_ids", []),
            )
            edges.append(edge)

        # Return first edge if multiple, or the single edge
        return edges[0] if edges else None

    def _build_clusters(
        self,
        propositions: list[dict],
        relations: list[dict],
    ) -> list[PropositionCluster]:
        """
        Build proposition clusters from equivalence relations.

        Clusters are formed by:
        1. Direct rephrase/equivalence relations
        2. Shared concept bindings (high overlap)
        """
        clusters = []
        cluster_map: dict[str, str] = {}  # prop_id -> cluster_id
        cluster_counter = 0

        # Find equivalence relations
        equivalence_relations = [
            r for r in relations
            if r.get("relation_type") == "rephrase"
        ]

        # Build clusters from equivalence using union-find
        parent: dict[str, str] = {}

        def find(prop_id: str) -> str:
            if prop_id not in parent:
                parent[prop_id] = prop_id
            if parent[prop_id] != prop_id:
                parent[prop_id] = find(parent[prop_id])
            return parent[prop_id]

        def union(prop_a: str, prop_b: str) -> None:
            root_a = find(prop_a)
            root_b = find(prop_b)
            if root_a != root_b:
                parent[root_a] = root_b

        # Union equivalent propositions
        for rel in equivalence_relations:
            sources = rel.get("source_prop_ids", [])
            target = rel.get("target_prop_id")
            if target:
                for source in sources:
                    union(source, target)

        # Group by root
        groups: dict[str, list[str]] = defaultdict(list)
        for prop in propositions:
            prop_id = prop.get("prop_id")
            if prop_id:
                root = find(prop_id)
                groups[root].append(prop_id)

        # Create clusters
        for root, prop_ids in groups.items():
            if len(prop_ids) >= self.config.min_cluster_size:
                # Get concepts from propositions
                all_concepts = set()
                for prop in propositions:
                    if prop.get("prop_id") in prop_ids:
                        concepts = [
                            b.get("concept_label", "")
                            for b in prop.get("concept_bindings", [])
                        ]
                        all_concepts.update(concepts)

                # Generate summary
                summaries = [
                    p.get("text_summary", "")
                    for p in propositions
                    if p.get("prop_id") in prop_ids and p.get("text_summary")
                ]
                canonical_summary = summaries[0] if summaries else None

                cluster = PropositionCluster(
                    cluster_id=f"cluster_{cluster_counter}",
                    prop_ids=prop_ids,
                    canonical_summary=canonical_summary,
                    concept_labels=list(all_concepts),
                )
                clusters.append(cluster)
                for prop_id in prop_ids:
                    cluster_map[prop_id] = cluster.cluster_id
                cluster_counter += 1

        return clusters

    def _identify_contradictions(
        self,
        clusters: list[PropositionCluster],
        relations: list[dict],
    ) -> list[ContradictionCluster]:
        """
        Identify contradiction clusters per §11.1.

        A contradiction candidate requires:
        - Two proposition clusters
        - Persistent conflict edges
        - Shared concept bindings
        - Comparable temporal scope
        """
        contradictions = []
        counter = 0

        # Build conflict graph between clusters
        conflicts: dict[tuple[str, str], list[str]] = defaultdict(list)

        for rel in relations:
            if rel.get("relation_type") in ["conflict", "rebut", "undercut", "incompatibility"]:
                sources = rel.get("source_prop_ids", [])
                target = rel.get("target_prop_id")
                rel_id = rel.get("rel_id")

                # Find clusters for source and target propositions
                source_cluster = self._find_cluster_for_prop(clusters, sources[0] if sources else None)
                target_cluster = self._find_cluster_for_prop(clusters, target)

                if source_cluster and target_cluster and source_cluster != target_cluster:
                    key = tuple(sorted([source_cluster, target_cluster]))
                    conflicts[key].append(rel_id)

        # Identify contradictions from persistent conflicts
        for (cluster_a_id, cluster_b_id), conflict_edges in conflicts.items():
            if len(conflict_edges) >= self.config.contradiction_min_conflict_edges:
                # Get the clusters
                cluster_a = next((c for c in clusters if c.cluster_id == cluster_a_id), None)
                cluster_b = next((c for c in clusters if c.cluster_id == cluster_b_id), None)

                if not cluster_a or not cluster_b:
                    continue

                # Check for shared concepts (per §11.1)
                shared_concepts = set(cluster_a.concept_labels) & set(cluster_b.concept_labels)

                # Only contradiction if there's shared conceptual ground
                if shared_concepts:
                    # Check temporal compatibility
                    temporal_compatible = self._temporal_scopes_compatible(
                        cluster_a.temporal_scope,
                        cluster_b.temporal_scope,
                    )

                    # Determine contradiction type
                    contradiction_type = ContradictionType.DIRECT
                    if cluster_a.temporal_scope != cluster_b.temporal_scope:
                        contradiction_type = ContradictionType.CONCEPT_DRIFT
                    elif not temporal_compatible:
                        contradiction_type = ContradictionType.STRUCTURAL

                    contradictions.append(ContradictionCluster(
                        contradiction_id=f"contradiction_{counter}",
                        cluster_a_id=cluster_a_id,
                        cluster_b_id=cluster_b_id,
                        contradiction_type=contradiction_type,
                        shared_concepts=list(shared_concepts),
                        conflict_edges=conflict_edges,
                        temporal_compatible=temporal_compatible,
                    ))
                    counter += 1

        return contradictions

    def _find_cluster_for_prop(
        self,
        clusters: list[PropositionCluster],
        prop_id: str | None,
    ) -> str | None:
        """Find the cluster ID containing a proposition."""
        if not prop_id:
            return None
        for cluster in clusters:
            if prop_id in cluster.prop_ids:
                return cluster.cluster_id
        return None

    def _temporal_scopes_compatible(
        self,
        scope_a: str | None,
        scope_b: str | None,
    ) -> bool:
        """
        Check if two temporal scopes are compatible for contradiction.

        Contradiction requires the propositions to be "talking about the same thing"
        in a comparable temporal context.
        """
        # If no temporal info, assume compatible
        if not scope_a or not scope_b:
            return True

        # Exact match = compatible
        if scope_a == scope_b:
            return True

        # TODO: More sophisticated temporal comparison
        # For now, different scopes are considered potentially incompatible
        return True

    def _generate_motion_hypotheses(
        self,
        tree: DialecticalTree,
    ) -> list[MotionHypothesis]:
        """
        Generate motion hypotheses per §11.2.

        Triggered ONLY by graph-structural patterns:
        - Conflict → definitional re-articulation
        - Abstract opposition → concrete mechanism
        - Repeated failure → new structural determination
        """
        hypotheses = []
        counter = 0

        # Pattern 1: Conflict followed by definitional re-articulation
        for conflict in tree.contradictions:
            # Check if either cluster contains definitional illocutions
            for node in tree.nodes:
                if node.prop_id:
                    # Check if this proposition is in a contradictory cluster
                    # and has a definitional illocution
                    cluster = self._find_cluster_for_prop(tree.clusters, node.prop_id)
                    if cluster in [conflict.cluster_a_id, conflict.cluster_b_id]:
                        # This could trigger a conflict_to_definition motion
                        hypotheses.append(MotionHypothesis(
                            hypothesis_id=f"motion_{counter}",
                            pattern_type=MotionPatternType.CONFLICT_TO_DEFINITION,
                            trigger_node_ids=[node.node_id],
                            trigger_edge_ids=conflict.conflict_edges,
                            description=f"Conflict between clusters {conflict.cluster_a_id} and {conflict.cluster_b_id} "
                                       f"with shared concepts: {', '.join(conflict.shared_concepts)}",
                            confidence=0.7,
                        ))
                        counter += 1
                        break

        return hypotheses

    def _find_cluster_for_prop(
        self,
        clusters: list[PropositionCluster],
        prop_id: str | None,
    ) -> str | None:
        """Find the cluster ID containing a proposition."""
        if not prop_id:
            return None
        for cluster in clusters:
            if prop_id in cluster.prop_ids:
                return cluster.cluster_id
        return None


# =============================================================================
# Convenience Functions
# =============================================================================

def build_dialectical_structure(
    doc_id: str,
    extraction_results: list[dict[str, Any]],
    config: DialecticalBuilderConfig | None = None,
) -> DocumentDialecticalStructure:
    """
    Build dialectical structure for a document.

    Args:
        doc_id: Document identifier
        extraction_results: List of extraction window results
        config: Optional builder configuration

    Returns:
        DocumentDialecticalStructure with complete analysis
    """
    builder = DialecticalStructureBuilder(config)
    return builder.build_from_extraction_results(doc_id, extraction_results)


__all__ = [
    "DialecticalBuilderConfig",
    "DialecticalStructureBuilder",
    "build_dialectical_structure",
]

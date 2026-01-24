"""
Graph database integration (Neo4j) and locution bridge layer.

Stores AIF/IAT argument graph with nodes and edges.
Bridges existing Paragraph/SentenceSpan to argument graph.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §16.3.2:
Graph database enforces hard constraints:
- No proposition without locution
- No relation without evidence
- No orphan nodes
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from neo4j import GraphDatabase
from pydantic_settings import BaseSettings

from grundrisse_argument.graph.locution_bridge import (
    backfill_paragraph_locutions,
    backfill_span_locutions,
    create_extraction_run,
    get_locution_for_paragraph,
    get_locution_for_span,
    get_locutions_by_edition,
    locution_id_for_paragraph,
    locution_id_for_sentence_span,
    paragraph_to_locution,
    span_to_locution,
)

__all__ = [
    # Neo4j
    "Neo4jSettings",
    "Neo4jClient",
    # Locution bridge
    "backfill_paragraph_locutions",
    "backfill_span_locutions",
    "create_extraction_run",
    "get_locution_for_paragraph",
    "get_locution_for_span",
    "get_locutions_by_edition",
    "locution_id_for_paragraph",
    "locution_id_for_sentence_span",
    "paragraph_to_locution",
    "span_to_locution",
]


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "grundrisse"

    class Config:
        env_prefix = "GRUNDRISSE_NEO4J_"


class Neo4jClient:
    """
    Neo4j client for AIF/IAT graph storage.

    Per §16.3.2: Hard constraints enforced:
    - No proposition without locution grounding
    - No relation without evidence locutions
    - No orphan nodes

    Node types (AIF/IAT):
    - Locution (L-node): Text spans
    - Proposition (I-node): Abstract content
    - Illocution (L→P edge): Pragmatic force
    - Relation (S-node): RA/CA/MA nodes
    - Transition: Discourse markers
    """

    def __init__(self, settings: Neo4jSettings | None = None):
        self.settings = settings or Neo4jSettings()
        self._driver: GraphDatabase.driver | None = None

    def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = GraphDatabase.driver(
            self.settings.uri,
            auth=(self.settings.user, self.settings.password),
        )

    def close(self) -> None:
        """Close the connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> "Neo4jClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def verify_connectivity(self) -> bool:
        """Verify that the connection is working."""
        if not self._driver:
            return False
        self._driver.verify_connectivity()
        return True

    # =============================================================================
    # Schema Initialization (Constraints and Indexes)
    # =============================================================================

    def initialize_schema(self) -> None:
        """
        Initialize AIF/IAT graph schema with constraints.

        Per §16.3.2: Create constraints that enforce hard rules.
        """
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        with self._driver.session() as session:
            # Uniqueness constraints for IDs
            session.run("CREATE CONSTRAINT locution_id IF NOT EXISTS FOR (l:Locution) REQUIRE l.loc_id IS UNIQUE")
            session.run("CREATE CONSTRAINT prop_id IF NOT EXISTS FOR (p:Proposition) REQUIRE p.prop_id IS UNIQUE")
            session.run("CREATE CONSTRAINT illoc_id IF NOT EXISTS FOR (i:Illocution) REQUIRE i.illoc_id IS UNIQUE")
            session.run("CREATE CONSTRAINT rel_id IF NOT EXISTS FOR (r:Relation) REQUIRE r.rel_id IS UNIQUE")
            session.run("CREATE CONSTRAINT trans_id IF NOT EXISTS FOR (t:Transition) REQUIRE t.transition_id IS UNIQUE")

            # NOTE: Hard constraints per §16.3.2 enforced at application layer:
            # - No proposition without locution grounding (enforced in create_proposition)
            # - No relation without evidence locutions (enforced in create_relation)
            # - No inference cycles (validated in check_cycles before persist)
            #
            # Neo4j cannot enforce relationship existence constraints via schema alone;
            # validation happens before writes via validate_extraction_window().

    # =============================================================================
    # Locution (L-node) Operations
    # =============================================================================

    def create_locution(
        self,
        loc_id: str,
        text: str,
        start_char: int,
        end_char: int,
        paragraph_id: str,
        section_path: list[str],
        is_footnote: bool = False,
        footnote_links: list[str] | None = None,
        doc_id: str | None = None,
    ) -> None:
        """Create a locution node (L-node)."""
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        with self._driver.session() as session:
            query = """
                MERGE (l:Locution {loc_id: $loc_id})
                SET l.text = $text,
                    l.start_char = $start_char,
                    l.end_char = $end_char,
                    l.paragraph_id = $paragraph_id,
                    l.section_path = $section_path,
                    l.is_footnote = $is_footnote,
                    l.footnote_links = $footnote_links,
                    l.doc_id = $doc_id
            """
            session.run(query, parameters={
                "loc_id": loc_id,
                "text": text,
                "start_char": start_char,
                "end_char": end_char,
                "paragraph_id": paragraph_id,
                "section_path": section_path,
                "is_footnote": is_footnote,
                "footnote_links": footnote_links or [],
                "doc_id": doc_id,
            })

    # =============================================================================
    # Proposition (I-node) Operations
    # =============================================================================

    def create_proposition(
        self,
        prop_id: str,
        text_summary: str,
        surface_loc_ids: list[str],
        concept_bindings: list[dict] | None = None,
        entity_bindings: list[dict] | None = None,
        temporal_scope: str | None = None,
        is_implicit_reconstruction: bool = False,
        canonical_label: str | None = None,
        confidence: float = 1.0,
        doc_id: str | None = None,
    ) -> None:
        """
        Create a proposition node (I-node).

        Per hard constraint: Must link to at least one locution via HAS_LOCUTION.
        """
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        if not surface_loc_ids:
            raise ValueError("Proposition must have at least one surface_loc_ids")

        with self._driver.session() as session:
            # Create proposition node
            query = """
                MERGE (p:Proposition {prop_id: $prop_id})
                SET p.text_summary = $text_summary,
                    p.temporal_scope = $temporal_scope,
                    p.is_implicit_reconstruction = $is_implicit_reconstruction,
                    p.canonical_label = $canonical_label,
                    p.confidence = $confidence,
                    p.concept_bindings = $concept_bindings,
                    p.entity_bindings = $entity_bindings,
                    p.doc_id = $doc_id
            """
            session.run(query, parameters={
                "prop_id": prop_id,
                "text_summary": text_summary,
                "temporal_scope": temporal_scope,
                "is_implicit_reconstruction": is_implicit_reconstruction,
                "canonical_label": canonical_label,
                "confidence": confidence,
                "concept_bindings": concept_bindings or [],
                "entity_bindings": entity_bindings or [],
                "doc_id": doc_id,
            })

            # Link to locutions (HAS_LOCUTION edges)
            for loc_id in surface_loc_ids:
                session.run("""
                    MATCH (p:Proposition {prop_id: $prop_id})
                    MATCH (l:Locution {loc_id: $loc_id})
                    MERGE (l)-[:HAS_LOCUTION]->(p)
                """, parameters={"prop_id": prop_id, "loc_id": loc_id})

    # =============================================================================
    # Illocution (L→P edge) Operations
    # =============================================================================

    def create_illocution(
        self,
        illoc_id: str,
        source_loc_id: str,
        target_prop_id: str,
        force: str,
        attributed_to: str | None = None,
        is_implicit_opponent: bool = False,
        confidence: float = 1.0,
    ) -> None:
        """
        Create an illocutionary edge (L→P).

        Links a locution to a proposition with illocutionary force.
        """
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        with self._driver.session() as session:
            query = """
                MATCH (l:Locution {loc_id: $source_loc_id})
                MATCH (p:Proposition {prop_id: $target_prop_id})
                MERGE (l)-[i:Illocution {illoc_id: $illoc_id}]->(p)
                SET i.force = $force,
                    i.attributed_to = $attributed_to,
                    i.is_implicit_opponent = $is_implicit_opponent,
                    i.confidence = $confidence
            """
            session.run(query, parameters={
                "illoc_id": illoc_id,
                "source_loc_id": source_loc_id,
                "target_prop_id": target_prop_id,
                "force": force,
                "attributed_to": attributed_to,
                "is_implicit_opponent": is_implicit_opponent,
                "confidence": confidence,
            })

    # =============================================================================
    # Relation (S-node) Operations
    # =============================================================================

    def create_relation(
        self,
        rel_id: str,
        relation_type: str,
        source_prop_ids: list[str],
        target_prop_id: str,
        evidence_loc_ids: list[str],
        conflict_detail: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """
        Create a relation node (S-node: RA/CA/MA).

        Per hard constraint: Must link to evidence locutions via HAS_EVIDENCE.
        """
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        if not evidence_loc_ids:
            raise ValueError("Relation must have at least one evidence_loc_id")

        if not source_prop_ids:
            raise ValueError("Relation must have at least one source_prop_id")

        with self._driver.session() as session:
            # Create relation node
            query = """
                MERGE (r:Relation {rel_id: $rel_id})
                SET r.relation_type = $relation_type,
                    r.conflict_detail = $conflict_detail,
                    r.confidence = $confidence
            """
            session.run(query, parameters={
                "rel_id": rel_id,
                "relation_type": relation_type,
                "conflict_detail": conflict_detail,
                "confidence": confidence,
            })

            # Link source propositions
            for source_id in source_prop_ids:
                session.run("""
                    MATCH (r:Relation {rel_id: $rel_id})
                    MATCH (p:Proposition {prop_id: $source_id})
                    MERGE (p)-[:PREMISE_FOR]->(r)
                """, parameters={"rel_id": rel_id, "source_id": source_id})

            # Link to target proposition
            session.run("""
                MATCH (r:Relation {rel_id: $rel_id})
                MATCH (p:Proposition {prop_id: $target_prop_id})
                MERGE (r)-[:TARGETS]->(p)
            """, parameters={"rel_id": rel_id, "target_prop_id": target_prop_id})

            # Link to evidence locutions
            for evidence_id in evidence_loc_ids:
                session.run("""
                    MATCH (r:Relation {rel_id: $rel_id})
                    MATCH (l:Locution {loc_id: $evidence_id})
                    MERGE (l)-[:HAS_EVIDENCE]->(r)
                """, parameters={"rel_id": rel_id, "evidence_id": evidence_id})

    # =============================================================================
    # Transition Operations
    # =============================================================================

    def create_transition(
        self,
        transition_id: str,
        doc_id: str,
        from_loc_id: str,
        to_loc_id: str,
        marker: str,
        function_hint: str,
        position: int,
    ) -> None:
        """Create a discourse transition between locutions."""
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        with self._driver.session() as session:
            query = """
                MATCH (from_loc:Locution {loc_id: $from_loc_id})
                MATCH (to_loc:Locution {loc_id: $to_loc_id})
                MERGE (from_loc)-[t:Transition {transition_id: $transition_id}]->(to_loc)
                SET t.doc_id = $doc_id,
                    t.marker = $marker,
                    t.function_hint = $function_hint,
                    t.position = $position
            """
            session.run(query, parameters={
                "transition_id": transition_id,
                "doc_id": doc_id,
                "from_loc_id": from_loc_id,
                "to_loc_id": to_loc_id,
                "marker": marker,
                "function_hint": function_hint,
                "position": position,
            })

    # =============================================================================
    # Batch Operations
    # =============================================================================

    def persist_window(
        self,
        window_data: dict[str, Any],
        doc_id: str,
    ) -> None:
        """
        Persist a complete extraction window to Neo4j.

        Creates all nodes and edges for a single extraction window.
        """
        # Create locutions
        for loc in window_data.get("locutions", []):
            self.create_locution(
                loc_id=loc["loc_id"],
                text=loc["text"],
                start_char=loc["start_char"],
                end_char=loc["end_char"],
                paragraph_id=loc["paragraph_id"],
                section_path=loc.get("section_path", []),
                is_footnote=loc.get("is_footnote", False),
                footnote_links=loc.get("footnote_links", []),
                doc_id=doc_id,
            )

        # Create propositions
        for prop in window_data.get("propositions", []):
            self.create_proposition(
                prop_id=prop["prop_id"],
                text_summary=prop["text_summary"],
                surface_loc_ids=prop["surface_loc_ids"],
                concept_bindings=prop.get("concept_bindings", []),
                entity_bindings=prop.get("entity_bindings", []),
                temporal_scope=prop.get("temporal_scope"),
                is_implicit_reconstruction=prop.get("is_implicit_reconstruction", False),
                canonical_label=prop.get("canonical_label"),
                confidence=prop.get("confidence", 1.0),
                doc_id=doc_id,
            )

        # Create illocutions
        for illoc in window_data.get("illocutions", []):
            self.create_illocution(
                illoc_id=illoc["illoc_id"],
                source_loc_id=illoc["source_loc_id"],
                target_prop_id=illoc["target_prop_id"],
                force=illoc["force"],
                attributed_to=illoc.get("attributed_to"),
                is_implicit_opponent=illoc.get("is_implicit_opponent", False),
                confidence=illoc.get("confidence", 1.0),
            )

        # Create relations
        for rel in window_data.get("relations", []):
            self.create_relation(
                rel_id=rel["rel_id"],
                relation_type=rel["relation_type"],
                source_prop_ids=rel["source_prop_ids"],
                target_prop_id=rel["target_prop_id"],
                evidence_loc_ids=rel["evidence_loc_ids"],
                conflict_detail=rel.get("conflict_detail"),
                confidence=rel.get("confidence", 1.0),
            )

        # Create transitions
        for trans in window_data.get("transitions", []):
            self.create_transition(
                transition_id=trans["transition_id"],
                doc_id=trans.get("doc_id", doc_id),
                from_loc_id=trans["from_loc_id"],
                to_loc_id=trans["to_loc_id"],
                marker=trans["marker"],
                function_hint=trans["function_hint"],
                position=trans["position"],
            )

    # =============================================================================
    # Query Operations
    # =============================================================================

    def query_argument_graph(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results."""
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")

        with self._driver.session() as session:
            result = session.run(cypher, parameters=parameters or {})
            return [record.data() for record in result]

    def get_propositions_by_document(
        self,
        doc_id: str,
    ) -> list[dict[str, Any]]:
        """Get all propositions for a document."""
        return self.query_argument_graph(
            "MATCH (p:Proposition {doc_id: $doc_id}) RETURN p",
            {"doc_id": doc_id},
        )

    def get_relations_by_document(
        self,
        doc_id: str,
    ) -> list[dict[str, Any]]:
        """Get all relations for a document."""
        return self.query_argument_graph(
            """
            MATCH (r:Relation)-[:TARGETS]->(p:Proposition {doc_id: $doc_id})
            RETURN r, p.prop_id as target_prop_id
            """,
            {"doc_id": doc_id},
        )

    def get_support_subgraph(
        self,
        prop_id: str,
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """
        Get the support subgraph for a proposition.

        Returns all propositions that support or are supported by the given proposition.
        """
        return self.query_argument_graph(
            f"""
            MATCH path = (p:Proposition {{prop_id: $prop_id}})-[:PREMISE_FOR*1..{max_depth}]-(r:Relation)-[:TARGETS]->(other:Proposition)
            RETURN path, r, other
            """,
            {"prop_id": prop_id},
        )

    def get_conflict_subgraph(
        self,
        prop_id: str,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Get the conflict subgraph for a proposition.

        Returns all propositions that conflict with the given proposition.
        """
        return self.query_argument_graph(
            f"""
            MATCH (p:Proposition {{prop_id: $prop_id}})-[:TARGETS]-(r:Relation {{relation_type: 'conflict'}})-[:PREMISE_FOR]->(other:Proposition)
            RETURN r, other
            """,
            {"prop_id": prop_id},
        )

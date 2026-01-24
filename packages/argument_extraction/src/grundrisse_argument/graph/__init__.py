"""
Graph database integration (Neo4j).

Stores AIF/IAT argument graph with nodes and edges.
"""

from typing import Optional

from neo4j import GraphDatabase
from pydantic_settings import BaseSettings


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

    Hard constraints enforced:
    - No proposition without locution grounding
    - No relation without evidence locutions
    - No inference cycles within bounded windows
    """

    def __init__(self, settings: Optional[Neo4jSettings] = None):
        self.settings = settings or Neo4jSettings()
        self._driver: Optional[GraphDatabase.driver] = None

    def connect(self):
        """Establish connection to Neo4j."""
        self._driver = GraphDatabase.driver(
            self.settings.uri,
            auth=(self.settings.user, self.settings.password),
        )

    def close(self):
        """Close the connection."""
        if self._driver:
            self._driver.close()

    def verify_connectivity(self) -> bool:
        """Verify that the connection is working."""
        if not self._driver:
            return False
        self._driver.verify_connectivity()
        return True

    # TODO: Implement CRUD operations for nodes and edges
    # - create_locution()
    # - create_proposition()
    # - create_illocution()
    # - create_relation()
    # - create_transition()
    # - query_argument_graph()

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ontology_mcp.model import OntologyGraph

ALLOWED_NODE_LABELS = {"Repository", "Folder", "File", "Class", "Function", "Method", "Import"}
ALLOWED_REL_TYPES = {"CONTAINS", "DEFINES", "IMPORTS", "HAS_METHOD", "EXTENDS", "CALLS"}


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str
    database: str


def load_neo4j_config() -> Neo4jConfig:
    uri = os.environ.get("NEO4J_URI", "")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    if uri.startswith("neo4j+s://"):
        uri = uri.replace("neo4j+s://", "neo4j+ssc://", 1)
    elif uri.startswith("bolt+s://"):
        uri = uri.replace("bolt+s://", "bolt+ssc://", 1)
    return Neo4jConfig(uri=uri, username=username, password=password, database=database)


def _sanitize_props(props: dict[str, Any]) -> dict[str, Any]:
    """Keep only Neo4j-compatible scalar types; drop lists/dicts."""
    return {k: v for k, v in props.items() if v is None or isinstance(v, (str, int, float, bool))}


def write_graph_to_neo4j(
    graph: OntologyGraph,
    repo_id: str,
    config: Neo4jConfig,
    reset_graph: bool,
) -> dict[str, int]:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(config.uri, auth=(config.username, config.password))
    node_counter: Counter[str] = Counter()
    rel_counter: Counter[str] = Counter()

    try:
        with driver.session(database=config.database) as session:
            if reset_graph:
                session.run(
                    """
                    MATCH (r:Repository {id: $repo_id})
                    OPTIONAL MATCH (r)-[:CONTAINS*0..]->(n)
                    DETACH DELETE r, n
                    """,
                    repo_id=repo_id,
                )

            for node in graph.nodes.values():
                if node.type not in ALLOWED_NODE_LABELS:
                    continue
                # FIX: was node.props — correct field name is node.properties
                props = _sanitize_props(node.properties)
                session.run(
                    f"MERGE (n:{node.type} {{id: $id}}) SET n += $props",
                    id=node.id,
                    props=props,
                )
                node_counter[node.type] += 1

            for edge in graph.edges:
                if edge.rel_type not in ALLOWED_REL_TYPES:
                    continue
                # FIX: was edge.props — correct field name is edge.properties
                props = _sanitize_props(edge.properties)
                session.run(
                    f"""
                    MATCH (s {{id: $source_id}})
                    MATCH (t {{id: $target_id}})
                    MERGE (s)-[r:{edge.rel_type}]->(t)
                    SET r += $props
                    """,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    props=props,
                )
                rel_counter[edge.rel_type] += 1
    finally:
        driver.close()

    return {
        "nodes_written": sum(node_counter.values()),
        "relationships_written": sum(rel_counter.values()),
    }

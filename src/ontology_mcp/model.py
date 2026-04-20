"""
Core data model for the ontology graph.

The graph is a labelled property graph: nodes carry a type and a dict of
properties; edges carry a relationship type and an optional property dict.

Node types
----------
Repository  — root node, one per indexed repo
Folder      — directory in the repo
File        — source file
Class       — class / struct / interface definition
Function    — module-level or free function
Method      — function defined inside a class
Import      — external module/symbol imported by a file

Relationship types
------------------
CONTAINS    — structural containment (Repo→Folder, Folder→File, Class→Method)
DEFINES     — File defines a Class / Function
IMPORTS     — File imports a symbol or module
EXTENDS     — Class inherits from another Class
CALLS       — Function / Method calls another Function / Method
HAS_METHOD  — reserved; CONTAINS is used for class→method edges in practice
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

NodeType = Literal[
    "Repository",
    "Folder",
    "File",
    "Class",
    "Function",
    "Method",
    "Import",
]

RelationshipType = Literal[
    "CONTAINS",
    "DEFINES",
    "IMPORTS",
    "HAS_METHOD",
    "EXTENDS",
    "CALLS",
]


@dataclass(frozen=True)
class Node:
    """An immutable graph node identified by a stable SHA-1 ``id``."""

    id: str
    type: NodeType
    properties: dict


@dataclass(frozen=True)
class Edge:
    """An immutable directed edge between two nodes."""

    source_id: str
    rel_type: RelationshipType
    target_id: str
    properties: dict = field(default_factory=dict)


@dataclass
class OntologyGraph:
    """
    In-memory representation of the full ontology graph for one build pass.

    ``nodes`` is keyed by node id so that duplicate nodes from different
    parsing passes are naturally deduplicated.  ``edges`` is a list — the
    writer deduplicates them before persisting to SQLite.
    """

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        """Insert or replace a node by id."""
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        """Append an edge (deduplication happens at write time)."""
        self.edges.append(edge)

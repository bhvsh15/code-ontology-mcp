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
    id: str
    type: NodeType
    properties: dict


@dataclass(frozen=True)
class Edge:
    source_id: str
    rel_type: RelationshipType
    target_id: str
    properties: dict = field(default_factory=dict)


@dataclass
class OntologyGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

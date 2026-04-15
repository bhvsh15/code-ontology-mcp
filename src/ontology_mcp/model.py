from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#Valid types of nodes in the ontology graph
NodeType = Literal[
    "Repository",
    "Folder",
    "File",
    "Class",
    "Function",
    "Method",
    "Import",
]

#Valid types of relationships in the ontology graph
RelationshipType = Literal[
    "CONTAINS",
    "DEFINES",
    "IMPORTS",
    "HAS_METHOD",
    "EXTENDS",
    "CALLS",
]

#Model for a node in the ontology graph
@dataclass(frozen=True)
class Node:
    id: str
    type: NodeType
    properties: dict


#Model for an edge in the ontology graph
@dataclass(frozen=True)
class Edge:
    source_id: str
    rel_type: RelationshipType
    target_id: str
    properties: dict = field(default_factory=dict)


#Model for the ontology graph itself, Graph = (Nodes, Edges)
@dataclass
class OntologyGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

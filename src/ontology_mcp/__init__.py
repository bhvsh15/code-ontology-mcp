"""
ontology-mcp
============
A Model Context Protocol (MCP) server that indexes source code repositories
into a local SQLite graph and exposes tools for querying structure, call
chains, blast radius, and review context.

Supports Python (AST-based) and JavaScript / TypeScript / C# / Go / Rust
(tree-sitter based).  All graph data is stored in
``{repo_path}/.ontology-mcp/graph.db`` — no external database required.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"

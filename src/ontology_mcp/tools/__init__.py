"""
MCP tool implementations for ontology-mcp.

Each module in this package corresponds to one logical capability:

- ``build_python_code_ontology`` — scan & index a repo into SQLite
- ``query_graph``                — structural queries (overview, folder, file, symbol, call chain)
- ``blast_radius``               — impact analysis for changed files
- ``context_tools``              — compact summaries for agent orientation and code review
"""

__all__ = ["build_python_code_ontology"]

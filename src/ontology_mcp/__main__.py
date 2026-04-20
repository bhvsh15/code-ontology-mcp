"""
Entry point for ``python -m ontology_mcp``.

Allows the MCP server to be launched without the ``ontology-mcp-server``
console script, e.g.:

    python -m ontology_mcp
    PYTHONPATH=src python -m ontology_mcp
"""

from ontology_mcp.server import main


if __name__ == "__main__":
    main()

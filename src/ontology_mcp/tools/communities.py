"""
Tool: list_communities

What it does: Detects natural clusters in the codebase using the Louvain
community-detection algorithm (via networkx), then returns a ranked list of
communities with their member nodes, file spans, and auto-generated labels.

Use this to answer:
  - "What are the natural architectural layers of this codebase?"
  - "Which files are tightly coupled together?"
  - "Show me the clusters in the call graph."

The algorithm builds an undirected graph from CALLS / DEFINES / IMPORTS /
EXTENDS edges, then groups nodes into communities that maximise internal
density.  Results are saved to SQLite so subsequent calls are instant.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, build_communities, read_communities


# What it does: Detects communities and returns them ranked by size.
# Input: repo path, and optionally how many communities to show (default 20).
# Output: list of communities, each with a label, size, top nodes, and file list.
def get_list_communities(repo_path: str, top_n: int = 20) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    # Always rebuild — cheap enough and guarantees results are fresh
    build_result = build_communities(repo_path)
    if "error" in build_result:
        return build_result

    result = read_communities(repo_path, top_n=top_n)
    result["build"] = build_result
    return result
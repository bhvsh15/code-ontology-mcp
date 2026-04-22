"""
Tool: get_bridge_nodes

What it does: Finds nodes with high betweenness centrality — the chokepoints
that connect different communities in the codebase graph.

Use this to answer:
  - "Which files or functions are architectural chokepoints?"
  - "What would break the most if I changed X?"
  - "Where are the connectors between modules?"

The algorithm builds the same undirected graph as list_communities, then runs
betweenness centrality: a node scores high if it lies on many shortest paths
between other nodes — i.e. removing it would disconnect the graph the most.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, build_bridge_nodes, read_bridge_nodes


# What it does: Computes and returns the top bridge nodes ranked by betweenness centrality.
# Input: repo path, and optionally how many nodes to show (default 20).
# Output: ranked list of nodes with their betweenness score and file location.
def get_bridge_nodes(repo_path: str, top_n: int = 20) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    build_result = build_bridge_nodes(repo_path)
    if "error" in build_result:
        return build_result

    result = read_bridge_nodes(repo_path, top_n=top_n)
    result["build"] = build_result
    return result

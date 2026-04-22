"""
Tool: list_flows

What it does: Detects entry points in the codebase (functions with no inbound
CALLS edges — route handlers, main functions, CLI commands, etc.) and traces
each one outward via BFS to show its full execution path.

Use this to answer:
  - "What are all the entry points in this codebase?"
  - "What does calling login() trigger downstream?"
  - "Show me the execution path for each route handler."
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, build_flows, read_flows


# What it does: Detects entry points and returns their BFS call paths.
# Input: repo path, BFS depth limit, max entry points, max flows to return.
# Output: list of flows ranked by path length (longest first).
def get_list_flows(
    repo_path: str,
    max_depth: int = 5,
    max_entries: int = 20,
    top_n: int = 20,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    build_result = build_flows(repo_path, max_depth=max_depth, max_entries=max_entries)
    if "error" in build_result:
        return build_result

    result = read_flows(repo_path, top_n=top_n)
    result["build"] = build_result
    return result

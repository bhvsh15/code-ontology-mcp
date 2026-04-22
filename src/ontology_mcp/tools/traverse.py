"""
Tool: traverse_graph

What it does: Starts from any named node in the graph and walks outward
following the edge types you choose, up to a set number of hops.

More flexible than query_call_chain because it works across any edge type
(CALLS, IMPORTS, DEFINES, EXTENDS, CONTAINS) — not just function calls.

Use this to answer questions like:
  - "Show me everything login() touches directly and indirectly"
  - "What does this file import and what do those imports define?"
  - "What extends this base class?"
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, read_traverse

# Valid edge types the user can follow
VALID_EDGE_TYPES = {"CALLS", "DEFINES", "IMPORTS", "EXTENDS", "CONTAINS"}

# Valid directions
VALID_DIRECTIONS = {"out", "in", "both"}


# What it does: Validates inputs then delegates to read_traverse.
# Input: repo path, starting node name, edge types to follow,
#        direction (out/in/both), and max depth (1-5).
# Output: all reachable nodes and edges from the start node.
def get_traverse(
    repo_path: str,
    start: str,
    edge_types: list[str] | None = None,
    direction: str = "out",
    depth: int = 2,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
        }

    if direction not in VALID_DIRECTIONS:
        return {
            "error": f"Invalid direction '{direction}'. Choose from: {', '.join(VALID_DIRECTIONS)}",
        }

    if edge_types:
        invalid = [e for e in edge_types if e not in VALID_EDGE_TYPES]
        if invalid:
            return {
                "error": f"Invalid edge types: {invalid}. Valid options: {sorted(VALID_EDGE_TYPES)}",
            }

    if not (1 <= depth <= 5):
        return {"error": "depth must be between 1 and 5."}

    return read_traverse(
        repo_path=repo_path,
        start=start,
        edge_types=edge_types,
        direction=direction,
        depth=depth,
    )

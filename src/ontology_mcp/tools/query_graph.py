"""
Graph query tools — structural lookups against the SQLite ontology graph.

query_graph_overview  — node/edge counts + top-level structure
query               — single unified tool for folder / file / symbol lookups
query_call_chain    — callers / callees of a function up to N hops
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import (
    graph_exists,
    read_call_chain,
    read_file,
    read_folder,
    read_overview,
    read_symbol,
)

# Valid modes for the unified query tool
QUERY_MODES = ("file", "folder", "symbol")


# What it does: Checks if the graph exists, builds it if auto_build is True.
# Input: repo path and auto_build flag.
# Output: None if graph is ready, an error dict if not.
def _maybe_build(repo_path: str, auto_build: bool) -> dict | None:
    if graph_exists(repo_path):
        return None
    if not auto_build:
        return {
            "error": (
                f"No graph found for '{repo_path}'. "
                "Call build_python_code_ontology first, or pass auto_build=True."
            )
        }
    from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology
    result = build_python_code_ontology(repo_path=repo_path, dry_run=False)
    return {"auto_built": True, "build_summary": result}


# What it does: Returns high-level counts and top-level structure of the graph.
# Input: repo path.
# Output: node counts, edge counts, and top-level folder/file list.
def query_graph_overview(repo_path: str, auto_build: bool = False) -> dict:
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_overview(repo_path)
    if build_result:
        result["auto_build"] = build_result
    return result


# What it does: A single tool that handles file, folder, and symbol queries
# depending on the mode you choose.
# Input:
#   repo_path   — absolute path to the repo
#   mode        — "file", "folder", or "symbol"
#   target      — the path or name to query (file path, folder path, or symbol name)
#   symbol_type — only for mode="symbol", filters by "Class"/"Function"/"Method"
#   auto_build  — build the graph first if it doesn't exist
# Output: the subgraph for the requested file, folder, or symbol.
def query(
    repo_path: str,
    mode: str,
    target: str,
    symbol_type: str | None = None,
    auto_build: bool = False,
) -> dict:
    if mode not in QUERY_MODES:
        return {
            "error": f"Invalid mode '{mode}'. Choose from: {', '.join(QUERY_MODES)}",
            "examples": {
                "file":   "query(repo_path, mode='file',   target='backend/auth/auth_routes.py')",
                "folder": "query(repo_path, mode='folder', target='backend/routes')",
                "symbol": "query(repo_path, mode='symbol', target='login', symbol_type='Function')",
            },
        }

    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    if mode == "file":
        result = read_file(repo_path, target)
    elif mode == "folder":
        result = read_folder(repo_path, target)
    else:  # symbol
        result = read_symbol(repo_path, target, symbol_type)

    result["mode"] = mode
    result["target"] = target
    if build_result:
        result["auto_build"] = build_result
    return result


# What it does: Traces who calls a function (callers) or what it calls (callees),
# up to N hops away. Direction and depth are both configurable.
# Input: repo path, function name, direction (callers/callees/both), and max depth.
# Output: all functions in the call chain with the edges connecting them.
def query_call_chain(
    repo_path: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    auto_build: bool = False,
) -> dict:
    if direction not in ("callers", "callees", "both"):
        return {"error": f"Invalid direction '{direction}'. Use 'callers', 'callees', or 'both'."}
    if not (1 <= depth <= 10):
        return {"error": "depth must be between 1 and 10."}
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_call_chain(repo_path, symbol_name, direction, depth)
    result["direction"] = direction
    result["depth"] = depth
    if build_result:
        result["auto_build"] = build_result
    return result

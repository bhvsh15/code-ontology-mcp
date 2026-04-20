"""
Graph query tools — structural lookups against the SQLite ontology graph.

Each function corresponds to one MCP tool exposed via ``server.py``.  All
functions accept an optional ``auto_build`` flag: when True and the graph
is absent, the repo is indexed automatically before the query proceeds.

Query capabilities
------------------
query_graph_overview   — node/edge counts + top-level structure
query_folder           — all nodes and edges inside a folder subtree
query_file             — a file's symbols plus cross-file CALLS/EXTENDS edges
query_symbol           — a named class/function/method and its 1-hop neighbours
query_call_chain       — callers / callees of a function up to N hops
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


def _maybe_build(repo_path: str, auto_build: bool) -> dict | None:
    """
    Return None if the graph already exists.
    Return an error dict if it is missing and auto_build is False.
    Trigger a build and return a summary dict if auto_build is True.
    """
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


def query_graph_overview(repo_path: str, auto_build: bool = False) -> dict:
    """
    Return a high-level summary: node counts by type, edge counts by type,
    top-level folder/file entries, and the DB location.

    Parameters
    ----------
    repo_path:  Absolute path to the repository.
    auto_build: Index the repo first if no graph exists.
    """
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_overview(repo_path)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_folder(repo_path: str, folder_path: str, auto_build: bool = False) -> dict:
    """
    Return all nodes reachable from a folder via CONTAINS edges (files,
    classes, functions, methods) plus all edges between those nodes.

    Parameters
    ----------
    repo_path:   Absolute path to the repository.
    folder_path: Repo-relative posix path, e.g. ``"src/utils"``.
    auto_build:  Index the repo first if no graph exists.
    """
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_folder(repo_path, folder_path)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_file(repo_path: str, file_path: str, auto_build: bool = False) -> dict:
    """
    Return the subgraph for a single file: the file node, all symbols it
    defines, and any cross-file CALLS / EXTENDS edges touching those symbols
    (with the remote endpoint included as a node for context).

    Parameters
    ----------
    repo_path:  Absolute path to the repository.
    file_path:  Repo-relative path, e.g. ``"src/utils/helpers.py"``.
    auto_build: Index the repo first if no graph exists.
    """
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_file(repo_path, file_path)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_symbol(
    repo_path: str,
    symbol_name: str,
    symbol_type: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Find a class, function, or method by exact name and return it with its
    immediate (1-hop) relationships in all directions.

    Parameters
    ----------
    repo_path:   Absolute path to the repository.
    symbol_name: Exact name of the symbol (case-sensitive).
    symbol_type: Optional filter — ``"Class"``, ``"Function"``, or ``"Method"``.
    auto_build:  Index the repo first if no graph exists.
    """
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_symbol(repo_path, symbol_name, symbol_type)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_call_chain(
    repo_path: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    auto_build: bool = False,
) -> dict:
    """
    Return the CALLS subgraph around a named function or method.

    Parameters
    ----------
    repo_path:   Absolute path to the repository.
    symbol_name: Name of the function / method to start from.
    direction:
        ``"callees"`` — what this function calls (outbound).
        ``"callers"`` — who calls this function (inbound).
        ``"both"``    — both directions (default).
    depth:       Maximum CALLS hops to traverse, 1–10 (default 3).
    auto_build:  Index the repo first if no graph exists.
    """
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

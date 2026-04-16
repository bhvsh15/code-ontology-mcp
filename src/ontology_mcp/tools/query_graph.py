from __future__ import annotations

from pathlib import Path

from ontology_mcp.neo4j_reader import (
    GraphSlice,
    NodeRecord,
    EdgeRecord,
    load_neo4j_config,
    repo_exists_in_neo4j,
    read_graph_overview,
    read_folder_subgraph,
    read_file_subgraph,
    read_symbol,
    read_call_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_name_from_path(repo_path: str) -> str:
    return Path(repo_path).resolve().name


def _maybe_build(repo_name: str, repo_path: str | None, auto_build: bool) -> dict | None:
    """
    If the repo graph is absent from Neo4j and auto_build is True, trigger a
    build. Returns a build summary dict on success, or an error dict if the
    graph is missing and auto_build is False.
    Returns None if the graph already exists (no action needed).
    """
    config = load_neo4j_config()
    if repo_exists_in_neo4j(repo_name, config):
        return None  # graph present, nothing to do

    if not auto_build:
        return {
            "error": (
                f"No graph found for repo '{repo_name}' in Neo4j. "
                "Pass auto_build=True to build it automatically, "
                "or call build_python_code_ontology first."
            )
        }

    if not repo_path:
        return {
            "error": (
                f"No graph found for repo '{repo_name}' and no repo_path was provided "
                "to trigger auto_build. Please supply repo_path."
            )
        }

    # Lazy import to avoid circular dependency
    from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology
    result = build_python_code_ontology(repo_path=repo_path, dry_run=False)
    return {"auto_built": True, "build_summary": result}


def _slice_to_dict(s: GraphSlice) -> dict:
    return {
        "nodes": [
            {"id": n.id, "type": n.type, "properties": n.properties}
            for n in s.nodes
        ],
        "edges": [
            {
                "source_id": e.source_id,
                "rel_type": e.rel_type,
                "target_id": e.target_id,
                "properties": e.properties,
            }
            for e in s.edges
        ],
        "warnings": s.warnings,
        "node_count": len(s.nodes),
        "edge_count": len(s.edges),
    }


# ---------------------------------------------------------------------------
# Tool: query_graph_overview
# ---------------------------------------------------------------------------

def query_graph_overview(
    repo_name: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Return a high-level summary of the entire ontology graph for a repo:
    node counts by type, relationship counts by type, and top-level
    folder/file structure.

    If the graph is not yet in Neo4j:
    - auto_build=False (default): returns an error with instructions.
    - auto_build=True: triggers build_python_code_ontology first (requires repo_path).
    """
    build_result = _maybe_build(repo_name, repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    overview = read_graph_overview(repo_name)
    if build_result:
        overview["auto_build"] = build_result

    return overview


# ---------------------------------------------------------------------------
# Tool: query_folder
# ---------------------------------------------------------------------------

def query_folder(
    repo_name: str,
    folder_path: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Load the full subgraph for a specific folder within the repo.
    folder_path is the repo-relative posix path, e.g. "src/utils".

    Returns all nodes reachable from the folder via CONTAINS (files, classes,
    functions, methods) plus all edges between those nodes.
    """
    build_result = _maybe_build(repo_name, repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    result = _slice_to_dict(read_folder_subgraph(repo_name, folder_path))
    if build_result:
        result["auto_build"] = build_result
    return result


# ---------------------------------------------------------------------------
# Tool: query_file
# ---------------------------------------------------------------------------

def query_file(
    repo_name: str,
    file_path: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Load the subgraph for a single file: the file node, all symbols it defines
    (classes, functions, methods), and any cross-file CALLS / EXTENDS edges
    touching those symbols (with the remote endpoint node included for context).

    file_path is repo-relative, e.g. "src/utils/helpers.py".
    """
    build_result = _maybe_build(repo_name, repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    result = _slice_to_dict(read_file_subgraph(repo_name, file_path))
    if build_result:
        result["auto_build"] = build_result
    return result


# ---------------------------------------------------------------------------
# Tool: query_symbol
# ---------------------------------------------------------------------------

def query_symbol(
    repo_name: str,
    symbol_name: str,
    symbol_type: str | None = None,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Find a class, function, or method by name and return it with its immediate
    (1-hop) relationships in all directions.

    symbol_type: optional filter — "Class", "Function", or "Method".
    If omitted, all matching symbols are returned regardless of type.

    Useful for: "show me everything connected to class Foo",
                "where is function parse_line defined and who uses it?"
    """
    build_result = _maybe_build(repo_name, repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    result = _slice_to_dict(read_symbol(repo_name, symbol_name, symbol_type))
    if build_result:
        result["auto_build"] = build_result
    return result


# ---------------------------------------------------------------------------
# Tool: query_call_chain
# ---------------------------------------------------------------------------

def query_call_chain(
    repo_name: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Return the CALLS subgraph around a named function or method.

    direction:
      "callees" → what this function calls (outbound traversal)
      "callers" → who calls this function (inbound traversal)
      "both"    → both directions (default)

    depth: max hops to traverse (1–10, default 3).

    Useful for: impact analysis ("if I change X, what breaks?"),
                understanding a call chain ("how does request flow into X?").
    """
    if direction not in ("callers", "callees", "both"):
        return {"error": f"Invalid direction '{direction}'. Must be 'callers', 'callees', or 'both'."}
    if not (1 <= depth <= 10):
        return {"error": "depth must be between 1 and 10."}

    build_result = _maybe_build(repo_name, repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result

    result = _slice_to_dict(read_call_chain(repo_name, symbol_name, direction, depth))
    result["direction"] = direction
    result["depth"] = depth
    if build_result:
        result["auto_build"] = build_result
    return result
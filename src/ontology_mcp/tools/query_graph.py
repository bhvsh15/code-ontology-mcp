from __future__ import annotations

from ontology_mcp.sqlite_store import (
    graph_exists,
    read_overview,
    read_folder,
    read_file,
    read_symbol,
    read_call_chain,
)


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


def query_graph_overview(repo_path: str, auto_build: bool = False) -> dict:
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_overview(repo_path)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_folder(repo_path: str, folder_path: str, auto_build: bool = False) -> dict:
    build_result = _maybe_build(repo_path, auto_build)
    if build_result and "error" in build_result:
        return build_result
    result = read_folder(repo_path, folder_path)
    if build_result:
        result["auto_build"] = build_result
    return result


def query_file(repo_path: str, file_path: str, auto_build: bool = False) -> dict:
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
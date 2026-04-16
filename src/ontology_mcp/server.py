from __future__ import annotations

from fastmcp import FastMCP

from ontology_mcp.tools.build_python_code_ontology import (
    build_python_code_ontology as build_python_code_ontology_impl,
)
from ontology_mcp.tools.query_graph import (
    query_graph_overview as query_graph_overview_impl,
    query_folder as query_folder_impl,
    query_file as query_file_impl,
    query_symbol as query_symbol_impl,
    query_call_chain as query_call_chain_impl,
)

mcp = FastMCP(name="ontology-mcp")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@mcp.tool
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "ontology-mcp"}


# ---------------------------------------------------------------------------
# Build tool (existing)
# ---------------------------------------------------------------------------

@mcp.tool
def build_python_code_ontology(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    reset_graph: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Scan a Python repository, parse its AST, and write the resulting
    ontology graph to Neo4j.
    """
    return build_python_code_ontology_impl(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        reset_graph=reset_graph,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Query tools (new)
# ---------------------------------------------------------------------------

@mcp.tool
def query_graph_overview(
    repo_name: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Return a high-level summary of the ontology graph for a repository:
    node counts by type, relationship counts by type, and top-level
    folder/file structure.

    Args:
        repo_name:  The repository directory name (e.g. "my-project").
        repo_path:  Absolute path to the repo on disk. Required only when
                    auto_build=True and the graph does not yet exist.
        auto_build: If True and the graph is absent from Neo4j, build it
                    automatically before querying.
    """
    return query_graph_overview_impl(
        repo_name=repo_name,
        repo_path=repo_path,
        auto_build=auto_build,
    )


@mcp.tool
def query_folder(
    repo_name: str,
    folder_path: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Load the full subgraph for a specific folder within the repository.
    Returns all nodes (files, classes, functions, methods) reachable from
    the folder and all edges between them.

    Args:
        repo_name:   The repository directory name.
        folder_path: Repo-relative posix path to the folder, e.g. "src/utils".
        repo_path:   Absolute path to the repo on disk (needed for auto_build).
        auto_build:  Build the graph first if it is missing from Neo4j.
    """
    return query_folder_impl(
        repo_name=repo_name,
        folder_path=folder_path,
        repo_path=repo_path,
        auto_build=auto_build,
    )


@mcp.tool
def query_file(
    repo_name: str,
    file_path: str,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Load the subgraph for a single file: the file node, all symbols it defines
    (classes, functions, methods), and any cross-file CALLS/EXTENDS edges
    touching those symbols (with the remote endpoint included for context).

    Args:
        repo_name:  The repository directory name.
        file_path:  Repo-relative path to the file, e.g. "src/utils/helpers.py".
        repo_path:  Absolute path to the repo on disk (needed for auto_build).
        auto_build: Build the graph first if it is missing from Neo4j.
    """
    return query_file_impl(
        repo_name=repo_name,
        file_path=file_path,
        repo_path=repo_path,
        auto_build=auto_build,
    )


@mcp.tool
def query_symbol(
    repo_name: str,
    symbol_name: str,
    symbol_type: str | None = None,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Find a class, function, or method by name and return it with all its
    immediate (1-hop) relationships: what it defines, extends, calls, is
    called by, belongs to, etc.

    Args:
        repo_name:   The repository directory name.
        symbol_name: Exact name of the symbol (e.g. "parse_python_files").
        symbol_type: Optional type filter — "Class", "Function", or "Method".
                     Omit to match all types.
        repo_path:   Absolute path to the repo on disk (needed for auto_build).
        auto_build:  Build the graph first if it is missing from Neo4j.
    """
    return query_symbol_impl(
        repo_name=repo_name,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        repo_path=repo_path,
        auto_build=auto_build,
    )


@mcp.tool
def query_call_chain(
    repo_name: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    repo_path: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Return the CALLS subgraph around a named function or method, traversed
    up to `depth` hops.

    Args:
        repo_name:   The repository directory name.
        symbol_name: Name of the function/method to start from.
        direction:   "callees" — what this function calls (outbound).
                     "callers" — who calls this function (inbound).
                     "both"    — both directions (default).
        depth:       Maximum hops to traverse, 1–10 (default 3).
        repo_path:   Absolute path to the repo on disk (needed for auto_build).
        auto_build:  Build the graph first if it is missing from Neo4j.
    """
    return query_call_chain_impl(
        repo_name=repo_name,
        symbol_name=symbol_name,
        direction=direction,
        depth=depth,
        repo_path=repo_path,
        auto_build=auto_build,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
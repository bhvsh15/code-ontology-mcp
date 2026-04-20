from __future__ import annotations

import subprocess
from pathlib import Path

from fastmcp import FastMCP

from ontology_mcp.setup_env import ensure_env
from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.tools.blast_radius import get_blast_radius as get_blast_radius_impl
#Build and query tool implementations 
from ontology_mcp.tools.build_python_code_ontology import (build_python_code_ontology as build_python_code_ontology_impl,)
#Query tool implementations
from ontology_mcp.tools.query_graph import (
    query_graph_overview as query_graph_overview_impl,
    query_folder as query_folder_impl,
    query_file as query_file_impl,
    query_symbol as query_symbol_impl,
    query_call_chain as query_call_chain_impl,
)

ensure_env()

mcp = FastMCP(name="ontology-mcp")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@mcp.tool
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "ontology-mcp"}


@mcp.tool
def get_connection_info() -> dict:
    """
    Return everything an external agent needs to launch and connect to this
    MCP server — the uv command, absolute paths, and current Neo4j env status.
    """
    project_root = Path(__file__).resolve().parents[2]
    server_file = Path(__file__).resolve()

    uv_command = (
        f"uv run --project {project_root} ontology-mcp-server"
    )

    import os
    from ontology_mcp.setup_env import _REQUIRED
    tracked = list(_REQUIRED) + ["NEO4J_USERNAME", "NEO4J_DATABASE"]
    env_status = {
        var: "set" if os.environ.get(var, "").strip() else "MISSING"
        for var in tracked
    }

    return {
        "server_file": str(server_file),
        "project_root": str(project_root),
        "uv_command": uv_command,
        "mcp_config_file": str(project_root / "mcp-config.json"),
        "neo4j_env": env_status,
        "ready": all(v == "set" for v in [env_status[r] for r in _REQUIRED]),
    }


@mcp.tool
def get_changed_files(repo_path: str) -> dict:
    """
    Return the list of files that have uncommitted changes, are staged, or
    are untracked (excluding .gitignore'd files) in the given repository.

    Args:
        repo_path: Absolute path to a local git repository.

    Returns:
        A dict with:
          - repo_path: the resolved path that was inspected.
          - files:     deduplicated list of repo-relative paths.
          - count:     number of changed files.
          - warning:   present only when repo_path is not a git repository.
    """
    root = Path(repo_path).resolve()
    files = get_git_modified_files(repo_path)

    if not files:
        # Distinguish "clean repo" from "not a git repo" for the caller.
        is_git = False
        if root.is_dir():
            try:
                subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=root,
                    capture_output=True,
                    check=True,
                )
                is_git = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                is_git = False

        if not is_git:
            return {
                "repo_path": str(root),
                "files": [],
                "count": 0,
                "warning": f"{repo_path} is not a git repository.",
            }

    return {
        "repo_path": str(root),
        "files": files,
        "count": len(files),
    }


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

@mcp.tool
def get_blast_radius(
    repo_name: str,
    repo_path: str,
    depth: int = 3,
    file_paths: list[str] | None = None,
) -> dict:
    """
    Show what is affected by the current uncommitted changes in a repo.

    Traverses CALLS edges backwards from changed symbols to find every
    function, method, and class that depends on them — and which files
    those live in.

    Args:
        repo_name:  Repository directory name (must already be built in Neo4j).
        repo_path:  Absolute path to the repo on disk (used for git detection).
        depth:      Max CALLS hops to traverse, 1–10 (default 3).
        file_paths: Override git detection — pass explicit repo-relative paths.
    """
    return get_blast_radius_impl(
        repo_name=repo_name,
        repo_path=repo_path,
        depth=depth,
        file_paths=file_paths,
    )


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
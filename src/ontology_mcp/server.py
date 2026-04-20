from __future__ import annotations

import subprocess
from pathlib import Path

from fastmcp import FastMCP

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.tools.blast_radius import get_blast_radius as get_blast_radius_impl
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


@mcp.tool
def get_connection_info() -> dict:
    """
    Return everything an external agent needs to launch this MCP server.
    Storage is local SQLite — no database credentials required.
    """
    project_root = Path(__file__).resolve().parents[2]
    return {
        "server_file": str(Path(__file__).resolve()),
        "project_root": str(project_root),
        "uv_command": f"uv run --project {project_root} ontology-mcp-server",
        "mcp_config_file": str(project_root / "mcp-config.json"),
        "storage": "local SQLite (.ontology-mcp/graph.db inside each repo)",
        "credentials_required": False,
    }


@mcp.tool
def get_changed_files(repo_path: str) -> dict:
    """
    Return files with uncommitted changes, staged files, and untracked files
    (excluding .gitignore'd) in the given repository.

    Args:
        repo_path: Absolute path to a local git repository.
    """
    root = Path(repo_path).resolve()
    files = get_git_modified_files(repo_path)

    if not files:
        is_git = False
        if root.is_dir():
            try:
                subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=root, capture_output=True, check=True,
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

    return {"repo_path": str(root), "files": files, "count": len(files)}


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

@mcp.tool
def get_blast_radius(
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
        repo_path:  Absolute path to the repo on disk.
        depth:      Max CALLS hops to traverse, 1–10 (default 3).
        file_paths: Override git detection — pass explicit repo-relative paths.
    """
    return get_blast_radius_impl(repo_path=repo_path, depth=depth, file_paths=file_paths)


# ---------------------------------------------------------------------------
# Build
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
    ontology graph to a local SQLite database at {repo_path}/.ontology-mcp/graph.db.
    """
    return build_python_code_ontology_impl(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        reset_graph=reset_graph,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------

@mcp.tool
def query_graph_overview(repo_path: str, auto_build: bool = False) -> dict:
    """
    Return a high-level summary of the ontology graph for a repository:
    node counts by type, relationship counts by type, and top-level structure.

    Args:
        repo_path:  Absolute path to the repo on disk.
        auto_build: Build the graph automatically if it doesn't exist yet.
    """
    return query_graph_overview_impl(repo_path=repo_path, auto_build=auto_build)


@mcp.tool
def query_folder(repo_path: str, folder_path: str, auto_build: bool = False) -> dict:
    """
    Load the full subgraph for a specific folder within the repository.

    Args:
        repo_path:   Absolute path to the repo on disk.
        folder_path: Repo-relative path to the folder, e.g. "src/utils".
        auto_build:  Build the graph first if it is missing.
    """
    return query_folder_impl(repo_path=repo_path, folder_path=folder_path, auto_build=auto_build)


@mcp.tool
def query_file(repo_path: str, file_path: str, auto_build: bool = False) -> dict:
    """
    Load the subgraph for a single file: the file node, all symbols it defines,
    and any cross-file CALLS/EXTENDS edges.

    Args:
        repo_path:  Absolute path to the repo on disk.
        file_path:  Repo-relative path to the file, e.g. "src/utils/helpers.py".
        auto_build: Build the graph first if it is missing.
    """
    return query_file_impl(repo_path=repo_path, file_path=file_path, auto_build=auto_build)


@mcp.tool
def query_symbol(
    repo_path: str,
    symbol_name: str,
    symbol_type: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Find a class, function, or method by name and return it with its
    immediate (1-hop) relationships.

    Args:
        repo_path:   Absolute path to the repo on disk.
        symbol_name: Exact name of the symbol (e.g. "parse_python_files").
        symbol_type: Optional filter — "Class", "Function", or "Method".
        auto_build:  Build the graph first if it is missing.
    """
    return query_symbol_impl(
        repo_path=repo_path,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        auto_build=auto_build,
    )


@mcp.tool
def query_call_chain(
    repo_path: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    auto_build: bool = False,
) -> dict:
    """
    Return the CALLS subgraph around a named function or method.

    Args:
        repo_path:   Absolute path to the repo on disk.
        symbol_name: Name of the function/method to start from.
        direction:   "callees", "callers", or "both" (default).
        depth:       Maximum hops to traverse, 1–10 (default 3).
        auto_build:  Build the graph first if it is missing.
    """
    return query_call_chain_impl(
        repo_path=repo_path,
        symbol_name=symbol_name,
        direction=direction,
        depth=depth,
        auto_build=auto_build,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
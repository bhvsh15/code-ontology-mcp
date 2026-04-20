"""
Blast-radius analysis tool.

Given a repository path, determines which source files have uncommitted
changes (via git) and then traverses the CALLS graph backwards to find
every symbol and file that depends on those changed symbols.

The result answers the question: "If I commit what I have now, what else
in the codebase might break?"

Integration
-----------
- Uses ``git_utils.get_git_modified_files`` for change detection.
- Uses ``sqlite_store.read_blast_radius`` for graph traversal.
- Exposed as the ``get_blast_radius`` MCP tool via ``server.py``.
"""

from __future__ import annotations

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.sqlite_store import graph_exists, read_blast_radius


def get_blast_radius(
    repo_path: str,
    depth: int = 3,
    file_paths: list[str] | None = None,
) -> dict:
    """
    Return every symbol and file affected by the current uncommitted changes.

    Parameters
    ----------
    repo_path:
        Absolute path to the local repository.  The graph must already be
        built (``build_python_code_ontology`` must have been run).
    depth:
        Maximum number of CALLS hops to traverse when looking for callers.
        1 = direct callers only; default 3; max 10.
    file_paths:
        Override automatic git detection and use this explicit list of
        repo-relative file paths instead.  Useful for targeted analysis.

    Returns a dict with keys:
    - ``changed_files``          — files that were modified
    - ``changed_symbols``        — symbols defined in those files
    - ``affected_symbols``       — symbols that transitively call changed symbols
    - ``affected_files``         — unique files containing affected symbols
    - ``total_changed_symbols``
    - ``total_affected_symbols``
    - ``total_affected_files``
    - ``warnings``               — e.g. files not yet indexed in the graph
    """
    if not graph_exists(repo_path):
        return {
            "error": (
                f"No graph found for '{repo_path}'. "
                "Call build_python_code_ontology first."
            )
        }

    changed = file_paths if file_paths is not None else get_git_modified_files(repo_path)

    if not changed:
        return {
            "repo_path": repo_path,
            "message": "No changed files detected — nothing to analyse.",
            "changed_files": [],
            "changed_symbols": [],
            "affected_symbols": [],
            "affected_files": [],
            "total_changed_symbols": 0,
            "total_affected_symbols": 0,
            "total_affected_files": 0,
            "warnings": [],
        }

    return read_blast_radius(repo_path=repo_path, changed_file_paths=changed, depth=depth)

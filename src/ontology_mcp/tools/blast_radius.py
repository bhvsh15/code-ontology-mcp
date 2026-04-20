from __future__ import annotations

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.sqlite_store import graph_exists, read_blast_radius


def get_blast_radius(
    repo_path: str,
    depth: int = 3,
    file_paths: list[str] | None = None,
) -> dict:
    """
    Return every symbol and file affected by current uncommitted changes.

    If file_paths is provided those are used; otherwise git detects changed files.
    depth controls how many CALLS hops to traverse (1–10, default 3).
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
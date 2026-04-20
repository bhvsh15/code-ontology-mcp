from __future__ import annotations

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.neo4j_reader import read_blast_radius, repo_exists_in_neo4j, load_neo4j_config


def get_blast_radius(
    repo_name: str,
    repo_path: str,
    depth: int = 3,
    file_paths: list[str] | None = None,
) -> dict:
    """
    Return every symbol and file affected by current uncommitted changes in a repo.

    If file_paths is provided, those are used instead of auto-detecting via git.
    depth controls how many CALLS hops to traverse (1–10, default 3).
    """
    config = load_neo4j_config()

    if not repo_exists_in_neo4j(repo_name, config):
        return {
            "error": (
                f"No graph found for '{repo_name}'. "
                "Call build_python_code_ontology first."
            )
        }

    changed = file_paths if file_paths is not None else get_git_modified_files(repo_path)

    if not changed:
        return {
            "repo_name": repo_name,
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

    result = read_blast_radius(
        repo_name=repo_name,
        changed_file_paths=changed,
        depth=depth,
        config=config,
    )
    result["repo_path"] = repo_path
    return result
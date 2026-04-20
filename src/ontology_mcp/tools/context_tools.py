"""
Agent-oriented context tools.

Provides compact, token-efficient summaries designed to be called at the
*start* of an agent session.  Instead of forcing the agent to make 4-5
separate tool calls to understand a repo, these tools bundle the most
useful signal into a single response.

Tools
-----
get_minimal_context
    ~100-token orientation: node/edge counts, top folders, hotspot files.
    Should be the first call any agent makes before anything else.

get_review_context
    Pre-review bundle: changed files + blast radius + mini graph summary.
    Replaces calling get_changed_files → get_blast_radius → query_graph_overview
    separately, saving round trips and token overhead.
"""

from __future__ import annotations

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.sqlite_store import (
    graph_exists,
    read_blast_radius,
    read_minimal_context,
)


def get_minimal_context(repo_path: str) -> dict:
    """
    Return an ultra-compact graph summary (~100 tokens).

    Includes repo name, total node and edge counts by type, top-level
    folder names, and the 5 most-connected files (structural hotspots).

    Call this first — it tells the agent what is in the graph and which
    files are worth querying in more detail.

    Parameters
    ----------
    repo_path:
        Absolute path to the indexed repository.
    """
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
            "tip": "build_python_code_ontology(repo_path=...) to index the repo.",
        }
    return read_minimal_context(repo_path)


def get_review_context(repo_path: str, depth: int = 2) -> dict:
    """
    Return a token-optimised bundle of context for a code review session.

    Combines in one call:
    - A mini graph summary (same as ``get_minimal_context``)
    - The list of git-changed files
    - Blast-radius analysis at the requested CALLS depth

    Parameters
    ----------
    repo_path:
        Absolute path to the indexed repository.
    depth:
        CALLS traversal depth for blast-radius.  Default 2 keeps the
        response compact; increase to 3-5 for larger impact windows.
    """
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
        }

    changed = get_git_modified_files(repo_path)
    overview = read_minimal_context(repo_path)

    if not changed:
        return {
            "summary": overview,
            "changed_files": [],
            "blast_radius": None,
            "message": "No uncommitted changes detected.",
        }

    blast = read_blast_radius(repo_path=repo_path, changed_file_paths=changed, depth=depth)

    return {
        "summary": overview,
        "changed_files": changed,
        "blast_radius": {
            "changed_symbols": blast["changed_symbols"],
            "affected_symbols": blast["affected_symbols"],
            "affected_files": blast["affected_files"],
            "total_affected": blast["total_affected_symbols"],
        },
        "warnings": blast.get("warnings", []),
    }

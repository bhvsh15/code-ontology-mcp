"""
Tool: find_similar_implementations

What it does: Given the callees a new function needs to invoke, finds existing
functions in the codebase that already call those same symbols — ranked by
how many callees they share (overlap score).

Agent use case:
  Agent needs to write a new auth helper that calls hash_password and
  create_access_token. Instead of hallucinating the implementation, one call
  returns existing functions with the same call pattern to copy from.

Why this can't be derived from existing tools:
  Requires set intersection across CALLS edges for multiple targets simultaneously.
  A smart agent would need O(n) query_call_chain calls to approximate this.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, find_similar_implementations as find_similar_impl


# What it does: Finds existing functions with the most similar call pattern.
# Input: repo path, list of callee names the new function will call, max results.
# Output: ranked list with overlap score and matched callee names.
def get_similar_implementations(
    repo_path: str,
    callees: list[str],
    top_n: int = 10,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    if not callees:
        return {"error": "Provide at least one callee name."}

    return find_similar_impl(repo_path=repo_path, callees=callees, top_n=top_n)

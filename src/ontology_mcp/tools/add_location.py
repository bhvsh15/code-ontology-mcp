"""
Tool: get_add_location

What it does: Given a list of symbols a new function will interact with
(call or be called by), returns the best file to add it to — based on
community membership of those symbols.

Agent use case:
  Agent needs to add a new function that calls hash_password and
  create_access_token. Instead of scanning the codebase, one call returns
  "put it in backend/auth/auth_routes.py" with a confidence score and reasoning.

How it works:
  Looks up which file each referenced symbol lives in, runs a majority vote
  across files and communities, and returns the winner as the suggested location.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, get_add_location as get_add_location_impl


# What it does: Suggests the best file to add a new function to.
# Input: repo path, list of symbol names the new function will call or be called by.
# Output: suggested file, confidence score, reasoning, and alternative files.
def get_add_location(repo_path: str, symbols: list[str]) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    if not symbols:
        return {"error": "Provide at least one symbol name."}

    return get_add_location_impl(repo_path=repo_path, symbols=symbols)

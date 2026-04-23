"""
Tool: get_context_window_pack

What it does: Given a list of symbol names the agent is working with, returns
all their nodes, the edges between them, and their immediate external neighbors
— in a single batched call.

Agent use case:
  Agent is editing a feature that touches login, verify_password,
  create_access_token, and require_roles. Instead of 4 separate query() calls,
  one call returns the complete subgraph — internal relationships + external
  connections — deduplicated and ready to use.

Token savings:
  Replaces N query(mode="symbol") calls with 1 call. For N=5, saves ~4 round
  trips and the overhead of merging results manually.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, get_context_window_pack as get_pack_impl


# What it does: Batches multiple symbol lookups into one compact subgraph response.
# Input: repo path, list of symbol names.
# Output: resolved nodes, internal edges, external 1-hop neighbors, community membership.
def get_context_window_pack(repo_path: str, symbols: list[str]) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    if not symbols:
        return {"error": "Provide at least one symbol name."}

    return get_pack_impl(repo_path=repo_path, symbols=symbols)

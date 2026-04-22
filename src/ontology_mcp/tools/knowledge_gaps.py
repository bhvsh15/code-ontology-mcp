"""
Tool: get_knowledge_gaps

What it does: Finds weak spots in the codebase — symbols that are either
completely isolated (no connections) or high-traffic hotspots with no test coverage.

Use this to answer:
  - "What dead code or orphaned files exist in this repo?"
  - "Which critical functions have no tests?"
  - "Where are the riskiest untested parts of the codebase?"

Two gap types detected:
  - isolated:          nodes with 0 edges — dead code, orphaned files
  - untested_hotspot:  nodes with high degree (many connections) but no test_* callers
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, build_knowledge_gaps, read_knowledge_gaps


# What it does: Detects and returns knowledge gaps in the codebase.
# Input: repo path, and optionally the degree threshold for hotspot detection (default 5).
# Output: dict with isolated nodes and untested hotspots lists.
def get_knowledge_gaps(repo_path: str, hotspot_degree: int = 5) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    build_result = build_knowledge_gaps(repo_path, hotspot_degree=hotspot_degree)
    if "error" in build_result:
        return build_result

    result = read_knowledge_gaps(repo_path)
    result["build"] = build_result
    return result

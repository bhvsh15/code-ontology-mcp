"""
Tool: find_circular_dependencies

What it does: Detects circular import chains in the codebase by running cycle
detection on the IMPORTS graph. Returns every cycle as an ordered list of file
paths so the agent knows exactly which files form the circle.

Agent use case:
  Agent is refactoring a module and hits an ImportError. Instead of manually
  tracing imports across files, one call returns all circular chains — the agent
  knows exactly which imports to break and where.

Why this can't be derived from existing tools:
  Requires graph cycle detection (nx.simple_cycles) — an agent cannot do this
  through reasoning alone without reading every file and tracing imports mentally.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, find_circular_dependencies as find_cycles_impl


# What it does: Detects and returns all circular import chains in the repo.
# Input: repo path.
# Output: total cycle count + each cycle as an ordered list of file paths (loop closed).
def get_circular_dependencies(repo_path: str) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    return find_cycles_impl(repo_path=repo_path)

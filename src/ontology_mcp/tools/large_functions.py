"""
Tool: find_large_functions

What it does: Finds functions and methods in the codebase that are longer
than a given number of lines. Large functions are harder to read, test,
and maintain — this tool helps identify them quickly.

Use this to answer questions like:
  - "Which functions should I refactor first?"
  - "Are there any functions over 100 lines in this repo?"
  - "What are the biggest methods in this codebase?"
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, read_large_functions


# What it does: Checks the graph exists, then returns all functions/methods
# that exceed the given line count threshold.
# Input: repo path, minimum lines to flag (default 50), and which types to check.
# Output: a sorted list of oversized symbols with their file, line range, and size.
def get_large_functions(
    repo_path: str,
    min_lines: int = 50,
    node_types: list[str] | None = None,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
        }

    results = read_large_functions(repo_path, min_lines=min_lines, node_types=node_types)

    return {
        "repo_path": repo_path,
        "min_lines": min_lines,
        "total_found": len(results),
        "functions": results,
    }

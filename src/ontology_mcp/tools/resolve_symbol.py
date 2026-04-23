"""
Tool: resolve_symbol

What it does: Given a symbol name and the file the agent is currently editing,
returns the most relevant match using import chain resolution — eliminating
the need to read multiple files to figure out which definition is in scope.

Agent use case:
  Agent is editing "backend/auth/auth_routes.py" and sees a call to "get_db".
  That name exists in 4 files. One call to resolve_symbol returns only the one
  that auth_routes.py actually imports, with full location info.

Confidence levels returned:
  - same_file:        the symbol is defined in the current file itself
  - import_resolved:  the symbol lives in a file directly imported by current_file
  - same_community:   the symbol lives in the same architectural cluster
  - other:            no import relationship found — all candidates returned ranked
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import graph_exists, resolve_symbol as resolve_symbol_impl


# What it does: Resolves a symbol name to its most likely definition given the current file context.
# Input: repo path, symbol name, current file (repo-relative), optional type filter.
# Output: resolved best match + ranked list of other candidates.
def get_resolve_symbol(
    repo_path: str,
    symbol_name: str,
    current_file: str,
    symbol_type: str | None = None,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    return resolve_symbol_impl(
        repo_path=repo_path,
        symbol_name=symbol_name,
        current_file=current_file,
        symbol_type=symbol_type,
    )

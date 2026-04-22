"""
Tool: detect_changes

What it does: The primary code-review tool. Given current git changes,
produces a prioritised report of every symbol that needs review — ranked
by risk score, with test coverage gaps flagged.

Risk score (0.0 to 1.0):
  - Higher score = more dependents + no test coverage
  - 0.0–0.3 → low risk
  - 0.4–0.6 → medium risk
  - 0.7–1.0 → high risk, review carefully

Use this to answer:
  - "What do I need to review before committing?"
  - "Which of my changes are highest risk?"
  - "What has no test coverage that I just touched?"
"""

from __future__ import annotations

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.sqlite_store import graph_exists, read_detect_changes


# What it does: Auto-detects changed files via git, then returns a
# risk-scored report of every symbol affected by those changes.
# Input: repo path, and traversal depth (how many CALLS hops to follow).
# Output: prioritised list of symbols with risk scores, dependent counts,
#         and test coverage status.
def get_detect_changes(repo_path: str, depth: int = 3) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
        }

    changed = get_git_modified_files(repo_path)

    if not changed:
        return {
            "message": "No uncommitted changes detected — nothing to review.",
            "changed_files": [],
            "report": [],
            "total_symbols": 0,
        }

    return read_detect_changes(
        repo_path=repo_path,
        changed_file_paths=changed,
        depth=depth,
    )

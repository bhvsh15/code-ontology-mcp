"""
Tool: build_from_github_url

Clones a public GitHub repo (or pulls if already cloned) and builds the
ontology graph in one call. Repos are stored at ~/.ontology-mcp/repos/.
"""

from __future__ import annotations

from ontology_mcp.git_clone import clone_or_pull
from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology


def build_from_github_url(
    github_url: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    try:
        local_path, action = clone_or_pull(github_url)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Git operation failed: {e}"}

    result = build_python_code_ontology(
        repo_path=local_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        reset_graph=True,
        dry_run=dry_run,
    )

    result["github_url"] = github_url
    result["local_path"] = local_path
    result["git_action"] = action
    return result

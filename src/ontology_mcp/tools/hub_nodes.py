"""
Tool: get_hub_nodes

What it does: Finds the most connected symbols (functions, classes, methods)
in a repo's graph. The more connections a symbol has, the higher the risk
if it's changed — it's the architectural hotspot.

Use this to answer questions like:
  - "What are the most critical functions in this codebase?"
  - "If I had to review one file, which one has the most impact?"
  - "What should I avoid touching without a full test run?"
"""

from ontology_mcp.sqlite_store import graph_exists, read_hub_nodes


# What it does: Wraps read_hub_nodes with a guard check and returns
# the top N most-connected symbols in the repo.
# Input: repo path, how many results to return, and optionally which types to include.
# Output: a ranked list of symbols or an error if the graph hasn't been built yet.
def get_hub_nodes(
    repo_path: str,
    top_n: int = 10,
    node_types: list[str] | None = None,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first.",
        }

    hubs = read_hub_nodes(repo_path, top_n=top_n, node_types=node_types)

    return {
        "repo_path": repo_path,
        "total_returned": len(hubs),
        "hub_nodes": hubs,
    }

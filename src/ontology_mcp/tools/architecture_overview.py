"""
Tool: get_architecture_overview

What it does: Returns a single combined map of the codebase architecture —
communities, bridge nodes, and hub nodes in one call.

Use this to answer:
  - "Give me a high-level map of this codebase."
  - "What are the main modules and how are they connected?"
  - "Where are the critical chokepoints and the most connected symbols?"

Builds all three analyses if not already cached, then returns them together.
"""

from __future__ import annotations

from ontology_mcp.sqlite_store import (
    graph_exists,
    build_communities,
    read_communities,
    build_bridge_nodes,
    read_bridge_nodes,
    build_knowledge_gaps,
)
from ontology_mcp.tools.hub_nodes import get_hub_nodes


# What it does: Runs communities + bridge nodes + hub nodes and returns them combined.
# Input: repo path, and optional limits for each section.
# Output: dict with communities, bridge_nodes, and hub_nodes sections.
def get_architecture_overview(
    repo_path: str,
    top_communities: int = 10,
    top_bridge: int = 10,
    top_hubs: int = 10,
) -> dict:
    if not graph_exists(repo_path):
        return {
            "error": f"No graph found for '{repo_path}'. Run build_python_code_ontology first."
        }

    # Build all three (idempotent — cheap if already cached)
    comm_build = build_communities(repo_path)
    if "error" in comm_build:
        return comm_build

    bridge_build = build_bridge_nodes(repo_path)
    if "error" in bridge_build:
        return bridge_build

    # Read results
    communities = read_communities(repo_path, top_n=top_communities)
    bridge_nodes = read_bridge_nodes(repo_path, top_n=top_bridge)
    hub_nodes = get_hub_nodes(repo_path, top_n=top_hubs)

    return {
        "repo_path": repo_path,
        "summary": {
            "total_communities": communities.get("total_communities", 0),
            "total_bridge_nodes": bridge_nodes.get("total_bridge_nodes", 0),
        },
        "communities": communities.get("communities", []),
        "bridge_nodes": bridge_nodes.get("bridge_nodes", []),
        "hub_nodes": hub_nodes.get("hub_nodes", hub_nodes.get("nodes", [])),
    }

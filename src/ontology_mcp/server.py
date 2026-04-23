"""
MCP server entry point for ontology-mcp.

Registers all tool functions with a FastMCP instance and exposes them over
the Model Context Protocol so agents (Claude, Antigravity, Cursor, Codex,
etc.) can call them directly from chat.

Available tools
---------------
healthcheck              — confirm the server is running
get_connection_info      — return launch command and server metadata
get_changed_files        — list uncommitted / untracked files in a repo
get_minimal_context      — ultra-compact graph summary (~100 tokens)
get_review_context       — bundled review context (changed + blast radius)
get_blast_radius         — full impact analysis for changed files
build_python_code_ontology — scan & index a repo into local SQLite
query_graph_overview     — node/edge counts + top-level structure
query_folder             — subgraph for a folder
query_file               — subgraph for a single file
query_symbol             — symbol lookup with 1-hop neighbours
query_call_chain         — callers / callees traversal
get_hub_nodes            — most connected symbols, filterable by type (Class/Function/Method)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastmcp import FastMCP

from ontology_mcp.git_utils import get_git_modified_files
from ontology_mcp.tools.context_tools import (
    get_minimal_context as get_minimal_context_impl,
    get_review_context as get_review_context_impl,
)
from ontology_mcp.tools.blast_radius import get_blast_radius as get_blast_radius_impl
from ontology_mcp.tools.hub_nodes import get_hub_nodes as get_hub_nodes_impl
from ontology_mcp.tools.large_functions import get_large_functions as get_large_functions_impl
from ontology_mcp.tools.traverse import get_traverse as get_traverse_impl
from ontology_mcp.tools.detect_changes import get_detect_changes as get_detect_changes_impl
from ontology_mcp.tools.communities import get_list_communities as get_list_communities_impl
from ontology_mcp.tools.bridge_nodes import get_bridge_nodes as get_bridge_nodes_impl
from ontology_mcp.tools.knowledge_gaps import get_knowledge_gaps as get_knowledge_gaps_impl
from ontology_mcp.tools.architecture_overview import get_architecture_overview as get_architecture_overview_impl
from ontology_mcp.tools.flows import get_list_flows as get_list_flows_impl
from ontology_mcp.tools.resolve_symbol import get_resolve_symbol as get_resolve_symbol_impl
from ontology_mcp.tools.circular_dependencies import get_circular_dependencies as get_circular_dependencies_impl
from ontology_mcp.tools.add_location import get_add_location as get_add_location_impl
from ontology_mcp.tools.similar_implementations import get_similar_implementations as get_similar_implementations_impl
from ontology_mcp.tools.vulnerability_surface import get_vulnerability_surface as get_vulnerability_surface_impl
from ontology_mcp.tools.context_window_pack import get_context_window_pack as get_context_window_pack_impl
from ontology_mcp.tools.build_python_code_ontology import (
    build_python_code_ontology as build_python_code_ontology_impl,
)
from ontology_mcp.tools.query_graph import (
    query_graph_overview as query_graph_overview_impl,
    query as query_impl,
    query_call_chain as query_call_chain_impl,
)

mcp = FastMCP(name="ontology-mcp")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@mcp.tool
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "ontology-mcp"}


@mcp.tool
def get_connection_info() -> dict:
    """
    Return everything an external agent needs to launch this MCP server.
    Storage is local SQLite — no database credentials required.
    """
    project_root = Path(__file__).resolve().parents[2]
    return {
        "server_file": str(Path(__file__).resolve()),
        "project_root": str(project_root),
        "uv_command": f"uv run --project {project_root} ontology-mcp-server",
        "mcp_config_file": str(project_root / "mcp-config.json"),
        "storage": "local SQLite (.ontology-mcp/graph.db inside each repo)",
        "credentials_required": False,
    }


@mcp.tool
def get_changed_files(repo_path: str) -> dict:
    """
    Return files with uncommitted changes, staged files, and untracked files
    (excluding .gitignore'd) in the given repository.

    Args:
        repo_path: Absolute path to a local git repository.
    """
    root = Path(repo_path).resolve()
    files = get_git_modified_files(repo_path)

    if not files:
        is_git = False
        if root.is_dir():
            try:
                subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=root, capture_output=True, check=True,
                )
                is_git = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                is_git = False
        if not is_git:
            return {
                "repo_path": str(root),
                "files": [],
                "count": 0,
                "warning": f"{repo_path} is not a git repository.",
            }

    return {"repo_path": str(root), "files": files, "count": len(files)}


# ---------------------------------------------------------------------------
# Detect changes
# ---------------------------------------------------------------------------

@mcp.tool
def detect_changes(repo_path: str, depth: int = 3) -> dict:
    """
    Primary code-review tool. Auto-detects git changes and returns a
    risk-scored report of every symbol that needs review.

    Each symbol gets a risk score (0.0–1.0) based on:
    - How many other symbols depend on it
    - Whether it has any test coverage

    Args:
        repo_path: Absolute path to the repo on disk.
        depth:     How many CALLS hops to follow (default 3).
    """
    return get_detect_changes_impl(repo_path=repo_path, depth=depth)


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

@mcp.tool
def list_communities(repo_path: str, top_n: int = 20) -> dict:
    """
    Detect and return the natural clusters in the codebase.

    Uses the Louvain algorithm on CALLS / DEFINES / IMPORTS / EXTENDS edges
    to group symbols into communities that maximise internal density.
    Each community gets an auto-generated label and a list of its top nodes.

    Use this to understand the architectural layers of a codebase or to find
    files that are tightly coupled.

    Args:
        repo_path: Absolute path to the repo on disk.
        top_n:     How many communities to return, largest first (default 20).
    """
    return get_list_communities_impl(repo_path=repo_path, top_n=top_n)


# ---------------------------------------------------------------------------
# Bridge nodes
# ---------------------------------------------------------------------------

@mcp.tool
def get_bridge_nodes(repo_path: str, top_n: int = 20) -> dict:
    """
    Find architectural chokepoints in the codebase using betweenness centrality.

    A bridge node scores high if it lies on many shortest paths between other
    nodes — removing it would disconnect the graph the most. These are the
    files or functions that glue different parts of the codebase together.

    Use this to understand:
      - Which symbols are the most critical connectors across modules?
      - Where would a change have the widest blast radius?

    Args:
        repo_path: Absolute path to the repo on disk.
        top_n:     How many bridge nodes to return, highest score first (default 20).
    """
    return get_bridge_nodes_impl(repo_path=repo_path, top_n=top_n)


# ---------------------------------------------------------------------------
# Knowledge gaps
# ---------------------------------------------------------------------------

@mcp.tool
def get_knowledge_gaps(repo_path: str, hotspot_degree: int = 5) -> dict:
    """
    Find weak spots in the codebase — isolated nodes and untested hotspots.

    Detects two types of knowledge gaps:
      - isolated:          symbols with zero edges (dead code, orphaned files)
      - untested_hotspot:  high-traffic nodes (degree >= hotspot_degree) with
                           no test_* callers — critical code with no test coverage

    Use this to prioritise testing efforts or find dead code to clean up.

    Args:
        repo_path:       Absolute path to the repo on disk.
        hotspot_degree:  Minimum degree to qualify as a hotspot (default 5).
    """
    return get_knowledge_gaps_impl(repo_path=repo_path, hotspot_degree=hotspot_degree)


# ---------------------------------------------------------------------------
# Architecture overview
# ---------------------------------------------------------------------------

@mcp.tool
def get_architecture_overview(
    repo_path: str,
    top_communities: int = 10,
    top_bridge: int = 10,
    top_hubs: int = 10,
) -> dict:
    """
    Return a high-level architectural map of the codebase in one call.

    Combines three analyses:
      - communities:   natural clusters of tightly coupled files/symbols
      - bridge_nodes:  chokepoints that connect different communities
      - hub_nodes:     most connected symbols by degree

    Use this as the first call when exploring an unfamiliar codebase.

    Args:
        repo_path:       Absolute path to the repo on disk.
        top_communities: How many communities to include (default 10).
        top_bridge:      How many bridge nodes to include (default 10).
        top_hubs:        How many hub nodes to include (default 10).
    """
    return get_architecture_overview_impl(
        repo_path=repo_path,
        top_communities=top_communities,
        top_bridge=top_bridge,
        top_hubs=top_hubs,
    )


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

@mcp.tool
def list_flows(
    repo_path: str,
    max_depth: int = 5,
    max_entries: int = 20,
    top_n: int = 20,
) -> dict:
    """
    Detect entry points and trace their full execution paths via BFS.

    Entry points are functions with no inbound CALLS edges — route handlers,
    main functions, CLI commands, scheduled tasks, etc.
    Each flow is traced outward through CALLS edges up to max_depth hops.

    Use this to understand what each entry point triggers downstream.

    Args:
        repo_path:    Absolute path to the repo on disk.
        max_depth:    BFS depth limit per entry point (default 5).
        max_entries:  Max entry points to trace (default 20).
        top_n:        How many flows to return, longest first (default 20).
    """
    return get_list_flows_impl(
        repo_path=repo_path,
        max_depth=max_depth,
        max_entries=max_entries,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# Resolve symbol
# ---------------------------------------------------------------------------

@mcp.tool
def resolve_symbol(
    repo_path: str,
    symbol_name: str,
    current_file: str,
    symbol_type: str | None = None,
) -> dict:
    """
    Resolve a symbol name to its most likely definition given the file the agent
    is currently editing — without reading multiple files.

    Uses the import chain from current_file to determine which definition of the
    symbol is actually in scope. Returns a confidence level with each candidate:
      - import_resolved:  the symbol lives in a file current_file directly imports
      - same_community:   the symbol lives in the same architectural cluster
      - other:            no import relationship found

    Args:
        repo_path:    Absolute path to the repo on disk.
        symbol_name:  The name to resolve (e.g. "get_db", "UserSchema").
        current_file: Repo-relative path of the file being edited
                      (e.g. "backend/auth/auth_routes.py").
        symbol_type:  Optional filter — "Function", "Method", or "Class".
    """
    return get_resolve_symbol_impl(
        repo_path=repo_path,
        symbol_name=symbol_name,
        current_file=current_file,
        symbol_type=symbol_type,
    )


# ---------------------------------------------------------------------------
# Circular dependencies
# ---------------------------------------------------------------------------

@mcp.tool
def find_circular_dependencies(repo_path: str) -> dict:
    """
    Detect all circular import chains in the codebase.

    Runs cycle detection on the IMPORTS graph and returns every cycle as an
    ordered list of file paths showing exactly which files form the circle.

    Use this before refactoring modules, or when debugging ImportError caused
    by circular imports. The agent cannot derive this through reasoning alone.

    Args:
        repo_path: Absolute path to the repo on disk.
    """
    return get_circular_dependencies_impl(repo_path=repo_path)


# ---------------------------------------------------------------------------
# Add location
# ---------------------------------------------------------------------------

@mcp.tool
def get_add_location(repo_path: str, symbols: list[str]) -> dict:
    """
    Suggest the best file to add a new function to, based on community membership
    of the symbols it will interact with.

    Pass the names of functions/classes the new code will call or be called by.
    Returns the file where most of those symbols live, with a confidence score
    and alternative options.

    Use this before writing new code to avoid putting it in the wrong module.

    Args:
        repo_path: Absolute path to the repo on disk.
        symbols:   Names of symbols the new function will call or interact with.
                   Example: ["hash_password", "create_access_token", "login"]
    """
    return get_add_location_impl(repo_path=repo_path, symbols=symbols)


# ---------------------------------------------------------------------------
# Similar implementations
# ---------------------------------------------------------------------------

@mcp.tool
def find_similar_implementations(
    repo_path: str,
    callees: list[str],
    top_n: int = 10,
) -> dict:
    """
    Find existing functions that share the same call pattern as the one you are
    about to write — ranked by overlap score.

    Pass the names of functions/symbols the new code will call. Returns existing
    functions that already call those same symbols, so the agent can copy a real
    pattern instead of hallucinating an implementation.

    Args:
        repo_path: Absolute path to the repo on disk.
        callees:   Names of symbols the new function will call.
                   Example: ["hash_password", "create_access_token"]
        top_n:     How many matches to return (default 10).
    """
    return get_similar_implementations_impl(
        repo_path=repo_path,
        callees=callees,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# Vulnerability surface
# ---------------------------------------------------------------------------

@mcp.tool
def get_vulnerability_surface(
    repo_path: str,
    auth_keywords: list[str] | None = None,
) -> dict:
    """
    Find entry points with no auth function in their call chain.

    Scans all stored flows and flags entry points (route handlers, CLI commands,
    etc.) where no function matching auth patterns appears in the execution path.

    Default auth patterns checked: auth, login, require, role, permission,
    token, verify, validate, authenticate, authorize, jwt, oauth, session,
    credential, identity, guard.

    Run list_flows first to ensure entry points are up to date.

    Args:
        repo_path:      Absolute path to the repo on disk.
        auth_keywords:  Override the default auth keyword list.
    """
    return get_vulnerability_surface_impl(
        repo_path=repo_path,
        auth_keywords=auth_keywords,
    )


# ---------------------------------------------------------------------------
# Context window pack
# ---------------------------------------------------------------------------

@mcp.tool
def get_context_window_pack(repo_path: str, symbols: list[str]) -> dict:
    """
    Batch lookup for multiple symbols in one call — returns their nodes,
    internal relationships, and external 1-hop neighbors as a single subgraph.

    Use this instead of calling query(mode="symbol") N times when working on
    a task that touches multiple known symbols. Saves N-1 round trips and
    returns a deduplicated, merged view of all their relationships.

    Args:
        repo_path: Absolute path to the repo on disk.
        symbols:   List of symbol names to look up together.
                   Example: ["login", "verify_password", "require_roles"]
    """
    return get_context_window_pack_impl(repo_path=repo_path, symbols=symbols)


# ---------------------------------------------------------------------------
# Hub nodes
# ---------------------------------------------------------------------------

@mcp.tool
def get_hub_nodes(
    repo_path: str,
    top_n: int = 10,
    node_types: list[str] | None = None,
) -> dict:
    """
    Find the most connected symbols in the codebase.

    Returns symbols ranked by total connections (inbound + outbound).
    The more connections a symbol has, the higher the risk if it changes.

    Args:
        repo_path:   Absolute path to the repo on disk.
        top_n:       How many results to return (default 10).
        node_types:  Filter by type. Options: "Class", "Function", "Method".
                     Pass one, two, or all three. Defaults to all three.

    Examples:
        get_hub_nodes(repo_path="...", node_types=["Function"])
        get_hub_nodes(repo_path="...", node_types=["Class"], top_n=5)
    """
    return get_hub_nodes_impl(repo_path=repo_path, top_n=top_n, node_types=node_types)


# ---------------------------------------------------------------------------
# Large functions
# ---------------------------------------------------------------------------

@mcp.tool
def find_large_functions(
    repo_path: str,
    min_lines: int = 50,
    node_types: list[str] | None = None,
) -> dict:
    """
    Find functions and methods that exceed a given line count.

    Large functions are harder to read, test, and maintain.
    Use this to identify refactoring candidates.

    Args:
        repo_path:   Absolute path to the repo on disk.
        min_lines:   Minimum lines to flag (default 50).
        node_types:  Filter by "Function", "Method", or both (default both).

    Examples:
        find_large_functions(repo_path="...", min_lines=100)
        find_large_functions(repo_path="...", min_lines=30, node_types=["Method"])
    """
    return get_large_functions_impl(repo_path=repo_path, min_lines=min_lines, node_types=node_types)


# ---------------------------------------------------------------------------
# Traverse graph
# ---------------------------------------------------------------------------

@mcp.tool
def traverse_graph(
    repo_path: str,
    start: str,
    edge_types: list[str] | None = None,
    direction: str = "out",
    depth: int = 2,
) -> dict:
    """
    Start from any named node and walk the graph outward following chosen edge types.

    More flexible than query_call_chain — works across any edge type,
    not just function calls.

    Args:
        repo_path:   Absolute path to the repo on disk.
        start:       Name of the node to start from (e.g. "login", "auth_routes.py").
        edge_types:  Edges to follow. Options: CALLS, DEFINES, IMPORTS, EXTENDS, CONTAINS.
                     Defaults to CALLS + DEFINES + IMPORTS + EXTENDS.
        direction:   "out" (default), "in", or "both".
        depth:       How many hops to walk, 1–5 (default 2).

    Examples:
        traverse_graph(repo_path="...", start="login", edge_types=["CALLS"])
        traverse_graph(repo_path="...", start="schema.py", edge_types=["DEFINES"], direction="out")
    """
    return get_traverse_impl(
        repo_path=repo_path,
        start=start,
        edge_types=edge_types,
        direction=direction,
        depth=depth,
    )


# ---------------------------------------------------------------------------
# Context tools
# ---------------------------------------------------------------------------

@mcp.tool
def get_minimal_context(repo_path: str) -> dict:
    """
    Ultra-compact repo summary (~100 tokens). Call this FIRST before any
    other tool — returns node/edge counts, top folders, and hotspot files
    so you know what to query next.

    Args:
        repo_path: Absolute path to the repo on disk.
    """
    return get_minimal_context_impl(repo_path=repo_path)


@mcp.tool
def get_review_context(repo_path: str, depth: int = 2) -> dict:
    """
    Token-optimised context for code review. One call returns changed files,
    their symbols, blast radius, and a graph summary — saving 3-4 round trips.

    Args:
        repo_path: Absolute path to the repo on disk.
        depth:     CALLS traversal depth for blast radius (default 2).
    """
    return get_review_context_impl(repo_path=repo_path, depth=depth)


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

@mcp.tool
def get_blast_radius(
    repo_path: str,
    depth: int = 3,
    file_paths: list[str] | None = None,
) -> dict:
    """
    Show what is affected by the current uncommitted changes in a repo.

    Traverses CALLS edges backwards from changed symbols to find every
    function, method, and class that depends on them — and which files
    those live in.

    Args:
        repo_path:  Absolute path to the repo on disk.
        depth:      Max CALLS hops to traverse, 1–10 (default 3).
        file_paths: Override git detection — pass explicit repo-relative paths.
    """
    return get_blast_radius_impl(repo_path=repo_path, depth=depth, file_paths=file_paths)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@mcp.tool
def build_python_code_ontology(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    reset_graph: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Scan a Python repository, parse its AST, and write the resulting
    ontology graph to a local SQLite database at {repo_path}/.ontology-mcp/graph.db.
    """
    return build_python_code_ontology_impl(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        reset_graph=reset_graph,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------

@mcp.tool
def query_graph_overview(repo_path: str, auto_build: bool = False) -> dict:
    """
    Return a high-level summary of the ontology graph for a repository:
    node counts by type, relationship counts by type, and top-level structure.

    Args:
        repo_path:  Absolute path to the repo on disk.
        auto_build: Build the graph automatically if it doesn't exist yet.
    """
    return query_graph_overview_impl(repo_path=repo_path, auto_build=auto_build)


@mcp.tool
def query(
    repo_path: str,
    mode: str,
    target: str,
    symbol_type: str | None = None,
    auto_build: bool = False,
) -> dict:
    """
    Single query tool for looking up a file, folder, or symbol in the graph.

    Args:
        repo_path:   Absolute path to the repo on disk.
        mode:        What to look up — "file", "folder", or "symbol".
        target:      The path or name to query.
        symbol_type: Only for mode="symbol" — filter by "Class", "Function", or "Method".
        auto_build:  Build the graph first if it is missing.

    Examples:
        query(repo_path, mode="file",   target="backend/auth/auth_routes.py")
        query(repo_path, mode="folder", target="backend/routes")
        query(repo_path, mode="symbol", target="login", symbol_type="Function")
    """
    return query_impl(
        repo_path=repo_path,
        mode=mode,
        target=target,
        symbol_type=symbol_type,
        auto_build=auto_build,
    )


@mcp.tool
def query_call_chain(
    repo_path: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
    auto_build: bool = False,
) -> dict:
    """
    Return the CALLS subgraph around a named function or method.

    Args:
        repo_path:   Absolute path to the repo on disk.
        symbol_name: Name of the function/method to start from.
        direction:   "callees", "callers", or "both" (default).
        depth:       Maximum hops to traverse, 1–10 (default 3).
        auto_build:  Build the graph first if it is missing.
    """
    return query_call_chain_impl(
        repo_path=repo_path,
        symbol_name=symbol_name,
        direction=direction,
        depth=depth,
        auto_build=auto_build,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
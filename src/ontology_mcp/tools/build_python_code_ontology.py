from __future__ import annotations

from collections import Counter

from ontology_mcp.parser import parse_python_files
from ontology_mcp.scanner import scan_python_files
from ontology_mcp.sqlite_store import write_graph


def build_python_code_ontology(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    reset_graph: bool = True,
    dry_run: bool = False,
) -> dict:
    scan = scan_python_files(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )
    graph = parse_python_files(repo_path=scan.repo_path, files=scan.files)
    node_counts = Counter(node.type for node in graph.nodes.values())
    rel_counts = Counter(edge.rel_type for edge in graph.edges)

    write_summary = {"nodes_written": 0, "relationships_written": 0}
    store_status = "skipped (dry_run)"

    if not dry_run:
        write_summary = write_graph(graph, repo_path=scan.repo_path, reset=reset_graph)
        store_status = "written"

    return {
        "status": "completed" if not dry_run else "dry_run_completed",
        "repo_path": scan.repo_path,
        "files_scanned": len(scan.files),
        "sample_files": scan.files[:20],
        "excluded_dirs": scan.excluded_dirs,
        "reset_graph": reset_graph,
        "dry_run": dry_run,
        "node_counts": dict(node_counts),
        "relationship_counts": dict(rel_counts),
        "parse_warnings": graph.warnings,
        "store_status": store_status,
        **write_summary,
    }
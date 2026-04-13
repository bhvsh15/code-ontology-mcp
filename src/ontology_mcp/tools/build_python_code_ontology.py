from __future__ import annotations

from collections import Counter

from ontology_mcp.neo4j_writer import load_neo4j_config, write_graph_to_neo4j
from ontology_mcp.parser import parse_python_files
from ontology_mcp.scanner import scan_python_files


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
    repo_id = next(
        node.id for node in graph.nodes.values() if node.type == "Repository"
    )

    write_summary = {"nodes_written": 0, "relationships_written": 0}
    neo4j_status = "skipped (dry_run)"
    if not dry_run:
        config = load_neo4j_config()
        write_summary = write_graph_to_neo4j(
            graph=graph,
            repo_id=repo_id,
            config=config,
            reset_graph=reset_graph,
        )
        neo4j_status = "written"

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
        "neo4j_status": neo4j_status,
        **write_summary,
    }

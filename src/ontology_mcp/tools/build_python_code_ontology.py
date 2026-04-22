"""
Main build tool for the ontology-mcp pipeline.

Orchestrates the full indexing flow for a repository:

1. **Scan** — discover all supported source files (``scanner.scan_files``).
2. **Parse** — route each file to the appropriate parser:
   - ``.py``            → Python AST parser (``parser.parse_python_files``)
   - ``.js/.ts/.cs/...``→ tree-sitter parser (``ts_parser.parse_file``)
3. **Merge** — combine both parsers' output into a single ``OntologyGraph``.
4. **Write** — persist deduplicated nodes and edges to
   ``{repo_path}/.ontology-mcp/graph.db`` via ``sqlite_store.write_graph``.

The function is idempotent: re-running with ``reset_graph=True`` (default)
drops and rebuilds the graph from scratch.  ``dry_run=True`` skips the
write step, useful for validation and testing.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from ontology_mcp.model import Edge, Node, OntologyGraph
from ontology_mcp.parser import parse_python_files
from ontology_mcp.scanner import scan_files
from ontology_mcp.sqlite_store import write_graph, read_file_hashes, write_file_hashes
from ontology_mcp.ts_parser import EXT_TO_LANG, parse_file as ts_parse_file


def _stable_id(*parts: str) -> str:
    """SHA-1 based stable ID — same inputs always produce the same ID."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _build_graph(repo_path: str, files: list[str]) -> OntologyGraph:
    """
    Route each file to the correct parser and merge results into one graph.

    Python files are parsed first so that the Repository / Folder / File
    hierarchy they create becomes the base structure.  Non-Python files
    graft onto that hierarchy, re-using existing folder nodes by ID so
    there are no duplicates.
    """
    root = Path(repo_path).resolve()
    root_str = str(root)

    py_files = [f for f in files if Path(f).suffix.lower() == ".py"]
    ts_files = [f for f in files if Path(f).suffix.lower() in EXT_TO_LANG]

    # Python AST parser returns a fully populated OntologyGraph including
    # the Repository node and all folder/file hierarchy.
    graph = parse_python_files(repo_path=root_str, files=py_files) if py_files \
        else OntologyGraph()

    # Ensure a Repository node exists even when there are no Python files.
    repo_id = _stable_id("repo", root_str)
    if repo_id not in graph.nodes:
        graph.add_node(Node(
            id=repo_id,
            type="Repository",
            properties={"id": repo_id, "name": root.name, "path": root_str},
        ))

    # Tree-sitter: one file at a time, grafting onto the existing hierarchy.
    for file_path in ts_files:
        path = Path(file_path)
        rel = path.relative_to(root).as_posix()

        # Ensure every ancestor folder node exists and is linked.
        folder_parts = path.relative_to(root).parts[:-1]
        parent_id = repo_id
        for i, part in enumerate(folder_parts):
            folder_rel = "/".join(folder_parts[: i + 1])
            fid = _stable_id("folder", root_str, folder_rel)
            if fid not in graph.nodes:
                graph.add_node(Node(
                    id=fid,
                    type="Folder",
                    properties={"id": fid, "name": part, "path": folder_rel},
                ))
                graph.add_edge(Edge(parent_id, "CONTAINS", fid))
            parent_id = fid

        file_id = _stable_id("file", root_str, rel)
        if file_id not in graph.nodes:
            graph.add_node(Node(
                id=file_id,
                type="File",
                properties={
                    "id": file_id,
                    "name": path.name,
                    "path": rel,
                    "extension": path.suffix,
                    "language": EXT_TO_LANG.get(path.suffix.lower(), "unknown"),
                },
            ))
            graph.add_edge(Edge(parent_id, "CONTAINS", file_id))

        ts_parse_file(
            file_path=file_path,
            repo_root=root_str,
            graph=graph,
            file_node_id=file_id,
        )

    return graph


def build_python_code_ontology(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    reset_graph: bool = True,
    dry_run: bool = False,
    languages: list[str] | None = None,
) -> dict:
    """
    Scan, parse, and index a repository into a local SQLite graph.

    Parameters
    ----------
    repo_path:
        Absolute path to the repository root.
    include_globs:
        Whitelist of fnmatch patterns (repo-relative).  Defaults to all
        files for the requested languages.
    exclude_globs:
        Additional exclusion patterns on top of the defaults in config.py.
    reset_graph:
        Drop and rebuild the graph from scratch (default True).
        Set False for incremental updates (not yet implemented).
    dry_run:
        Parse and report counts without writing to disk.  Useful for
        validation and testing without side effects.
    languages:
        Restrict scanning to specific languages, e.g. ``["python", "go"]``.
        Defaults to all supported languages.

    Returns a summary dict including file/node/edge counts, language
    breakdown, parse warnings, and the final write status.
    """
    scan = scan_files(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        languages=languages,
    )

    # --- Incremental build: skip files whose content hasn't changed ---
    stored_hashes = {} if reset_graph else read_file_hashes(scan.repo_path)
    new_hashes: dict[str, str] = {}
    files_to_parse: list[str] = []
    files_skipped = 0

    for file_path in scan.files:
        rel = Path(file_path).relative_to(scan.repo_path).as_posix()
        current_hash = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
        new_hashes[rel] = current_hash
        if stored_hashes.get(rel) == current_hash:
            files_skipped += 1
        else:
            files_to_parse.append(file_path)

    graph = _build_graph(repo_path=scan.repo_path, files=files_to_parse)

    node_counts = Counter(node.type for node in graph.nodes.values())
    rel_counts = Counter(edge.rel_type for edge in graph.edges)

    write_summary = {"nodes_written": 0, "relationships_written": 0}
    store_status = "skipped (dry_run)"

    if not dry_run:
        write_summary = write_graph(graph, repo_path=scan.repo_path, reset=reset_graph)
        write_file_hashes(scan.repo_path, new_hashes)
        store_status = "written"

    return {
        "status": "completed" if not dry_run else "dry_run_completed",
        "repo_path": scan.repo_path,
        "files_scanned": len(scan.files),
        "files_parsed": len(files_to_parse),
        "files_skipped": files_skipped,
        "languages_found": scan.languages_found,
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

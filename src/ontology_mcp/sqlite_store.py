"""
SQLite persistence layer for the ontology graph.

Each repository gets its own database file at:
    {repo_path}/.ontology-mcp/graph.db

Schema
------
nodes   (id TEXT PRIMARY KEY, type TEXT, props TEXT)
edges   (rowid INTEGER PK, source_id, rel_type, target_id, props TEXT)

Both ``props`` columns store JSON.  Properties are restricted to scalar
types (str, int, float, bool, None) so SQLite can store them as JSON
without lossy conversion.

Key design decisions
--------------------
- **Deduplication on write**: ``write_graph`` deduplicates edges with a
  Python set before inserting.  The parser can emit the same structural
  edge multiple times (e.g. ``repo→folder CONTAINS`` for every file in
  that folder); deduplicating here keeps queries clean.
- **Recursive CTEs**: folder and file traversal uses ``WITH RECURSIVE``
  so depth-unlimited CONTAINS walks are expressed in a single SQL query.
- **No ORM**: direct ``sqlite3`` calls keep the dependency footprint
  minimal and make the SQL explicit and auditable.
- **WAL mode**: enabled on every connection for concurrent read safety.

Public API (used by tool layer)
--------------------------------
write_graph           — persist an OntologyGraph
graph_exists          — check whether a graph DB exists
read_overview         — high-level counts + top-level structure
read_minimal_context  — ultra-compact agent-orientation summary
read_folder           — subgraph rooted at a folder
read_file             — subgraph for one file + cross-file edges
read_symbol           — symbol + 1-hop neighbourhood
read_call_chain       — BFS CALLS traversal (callers/callees)
read_blast_radius     — reverse CALLS traversal from changed files
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ontology_mcp.model import OntologyGraph

DB_DIR = ".ontology-mcp"
DB_FILE = "graph.db"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

#Function to get the path to the database file for a given repository path
# What it does: Returns the full file path to the SQLite database for a repo.
# Input: path to the repo folder.
# Output: a Path object pointing to {repo}/.ontology-mcp/graph.db
def db_path(repo_path: str) -> Path:
    return Path(repo_path).resolve() / DB_DIR / DB_FILE

# Internal helper to connect to the SQLite database, creating it if necessary
def _connect(repo_path: str, create: bool = False) -> sqlite3.Connection:
    path = db_path(repo_path)
    if not create and not path.exists():
        raise FileNotFoundError(
            f"No graph found at {path}. "
            "Run build_python_code_ontology first."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# Internal helper to initialize the database schema if it doesn't exist
def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id   TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            props TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS edges (
            rowid     INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            rel_type  TEXT NOT NULL,
            target_id TEXT NOT NULL,
            props     TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS file_hashes (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS communities (
            node_id      TEXT PRIMARY KEY,
            community_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bridge_nodes (
            node_id     TEXT PRIMARY KEY,
            score       REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_gaps (
            node_id      TEXT PRIMARY KEY,
            gap_type     TEXT NOT NULL,
            detail       TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS flows (
            entry_id     TEXT PRIMARY KEY,
            path         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_edges_source  ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target  ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_rel     ON edges(rel_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_type    ON nodes(type);
        CREATE INDEX IF NOT EXISTS idx_communities_cid ON communities(community_id);
    """)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


# Public API: write an OntologyGraph to the SQLite database for a repo
# What it does: Takes the full in-memory graph and saves it to SQLite.
# Input: the OntologyGraph object, the repo path, and whether to wipe existing data first.
# Output: a summary dict showing how many nodes and edges were written.
def write_graph(graph: OntologyGraph, repo_path: str, reset: bool = True) -> dict:
    conn = _connect(repo_path, create=True)
    _bootstrap(conn)

    if reset:
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM nodes")

    node_count = 0
    for node in graph.nodes.values():
        props = {k: v for k, v in node.properties.items()
                 if v is None or isinstance(v, (str, int, float, bool))}
        conn.execute(
            "INSERT OR REPLACE INTO nodes(id, type, props) VALUES (?, ?, ?)",
            (node.id, node.type, json.dumps(props)),
        )
        node_count += 1

    # Deduplicate edges — the parser may emit the same structural edge
    # (e.g. repo→folder CONTAINS) once per file in the same folder.
    seen_edges: set[tuple[str, str, str]] = set()
    edge_count = 0
    for edge in graph.edges:
        key = (edge.source_id, edge.rel_type, edge.target_id)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        props = {k: v for k, v in edge.properties.items()
                 if v is None or isinstance(v, (str, int, float, bool))}
        conn.execute(
            "INSERT INTO edges(source_id, rel_type, target_id, props) VALUES (?, ?, ?, ?)",
            (edge.source_id, edge.rel_type, edge.target_id, json.dumps(props)),
        )
        edge_count += 1

    conn.commit()
    conn.close()
    return {"nodes_written": node_count, "relationships_written": edge_count}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Internal helper to convert a SQLite row to a node dict with properties
def _row_to_node(row: sqlite3.Row) -> dict:
    props = json.loads(row["props"])
    return {"id": row["id"], "type": row["type"], **props}

# Internal helper to extract a list of IDs from a list of SQLite rows
def _ids_from(rows: list[sqlite3.Row]) -> list[str]:
    return [r["id"] for r in rows]


# Internal helper to create a string of SQL placeholders for a list of IDs
def _placeholders(ids: list[str]) -> str:
    return ",".join("?" * len(ids))


# ---------------------------------------------------------------------------
# Read: existence check
# ---------------------------------------------------------------------------

# What it does: Checks whether a graph has been built for this repo.
# Input: repo path.
# Output: True if the database file exists, False if not.
def graph_exists(repo_path: str) -> bool:
    return db_path(repo_path).exists()


# ---------------------------------------------------------------------------
# Read: overview
# ---------------------------------------------------------------------------

# What it does: Returns a high-level summary of everything in the graph.
# Input: repo path.
# Output: node counts by type, edge counts by type, and the top-level folder/file list.
def read_overview(repo_path: str) -> dict:
    conn = _connect(repo_path)
    try:
        node_counts: dict[str, int] = {}
        for row in conn.execute("SELECT type, COUNT(*) AS cnt FROM nodes GROUP BY type"):
            node_counts[row["type"]] = row["cnt"]

        rel_counts: dict[str, int] = {}
        for row in conn.execute("SELECT rel_type, COUNT(*) AS cnt FROM edges GROUP BY rel_type"):
            rel_counts[row["rel_type"]] = row["cnt"]

        repo_row = conn.execute(
            "SELECT id, props FROM nodes WHERE type = 'Repository' LIMIT 1"
        ).fetchone()
        repo_props = json.loads(repo_row["props"]) if repo_row else {}

        top_level_rows = conn.execute("""
            SELECT n.id, n.type, n.props
            FROM edges e
            JOIN nodes repo ON repo.id = e.source_id AND repo.type = 'Repository'
            JOIN nodes n    ON n.id  = e.target_id
            WHERE e.rel_type = 'CONTAINS'
            ORDER BY n.type, json_extract(n.props, '$.path')
        """).fetchall()
        top_level = [
            {"path": json.loads(r["props"]).get("path"), "type": r["type"]}
            for r in top_level_rows
        ]

        return {
            "repo_name": repo_props.get("name"),
            "repo_path": repo_props.get("path"),
            "db_path": str(db_path(repo_path)),
            "node_counts": node_counts,
            "relationship_counts": rel_counts,
            "top_level_entries": top_level,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: folder subgraph
# ---------------------------------------------------------------------------

# What it does: Returns everything inside a specific folder — all files, classes, functions, and connections.
# Input: repo path, and the folder path relative to the repo root (e.g. "backend/routes").
# Output: all nodes and edges inside that folder.
def read_folder(repo_path: str, folder_path: str) -> dict:
    conn = _connect(repo_path)
    try:
        folder_row = conn.execute(
            "SELECT id FROM nodes WHERE type='Folder' AND json_extract(props,'$.path')=?",
            (folder_path,),
        ).fetchone()
        if not folder_row:
            return {"error": f"Folder '{folder_path}' not found. Check the path is repo-relative."}

        folder_id = folder_row["id"]

        # All nodes reachable via CONTAINS (recursive CTE)
        node_rows = conn.execute("""
            WITH RECURSIVE contained(id) AS (
                SELECT ? AS id
                UNION ALL
                SELECT e.target_id FROM edges e
                JOIN contained c ON e.source_id = c.id
                WHERE e.rel_type = 'CONTAINS'
            )
            SELECT n.id, n.type, n.props FROM nodes n JOIN contained c ON n.id = c.id
        """, (folder_id,)).fetchall()

        node_ids = [r["id"] for r in node_rows]
        nodes = [_row_to_node(r) for r in node_rows]

        ph = _placeholders(node_ids)
        edge_rows = conn.execute(f"""
            SELECT source_id, rel_type, target_id, props FROM edges
            WHERE source_id IN ({ph}) AND target_id IN ({ph})
        """, node_ids + node_ids).fetchall()

        edges = [
            {"source_id": r["source_id"], "rel_type": r["rel_type"],
             "target_id": r["target_id"], **json.loads(r["props"])}
            for r in edge_rows
        ]
        return {"nodes": nodes, "edges": edges, "warnings": []}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: file subgraph
# ---------------------------------------------------------------------------

# What it does: Returns everything a single file contains plus its cross-file connections.
# Input: repo path, and the file path relative to the repo root.
# Output: all symbols in the file plus cross-file CALLS and EXTENDS edges.
def read_file(repo_path: str, file_path: str) -> dict:
    conn = _connect(repo_path)
    try:
        file_row = conn.execute(
            "SELECT id FROM nodes WHERE type='File' AND json_extract(props,'$.path')=?",
            (file_path,),
        ).fetchone()
        if not file_row:
            return {"error": f"File '{file_path}' not found."}

        file_id = file_row["id"]

        # All symbols defined inside this file (DEFINES + CONTAINS, any depth)
        internal_rows = conn.execute("""
            WITH RECURSIVE defined(id) AS (
                SELECT ? AS id
                UNION ALL
                SELECT e.target_id FROM edges e
                JOIN defined d ON e.source_id = d.id
                WHERE e.rel_type IN ('DEFINES','CONTAINS')
            )
            SELECT n.id, n.type, n.props FROM nodes n JOIN defined d ON n.id = d.id
        """, (file_id,)).fetchall()

        internal_ids = [r["id"] for r in internal_rows]
        nodes = [_row_to_node(r) for r in internal_rows]

        ph = _placeholders(internal_ids)

        # Internal edges
        internal_edges = conn.execute(f"""
            SELECT source_id, rel_type, target_id, props FROM edges
            WHERE source_id IN ({ph}) AND target_id IN ({ph})
        """, internal_ids + internal_ids).fetchall()

        # Cross-file CALLS + EXTENDS edges
        cross_edges = conn.execute(f"""
            SELECT source_id, rel_type, target_id, props FROM edges
            WHERE rel_type IN ('CALLS','EXTENDS')
              AND (
                (source_id IN ({ph}) AND target_id NOT IN ({ph}))
                OR
                (target_id IN ({ph}) AND source_id NOT IN ({ph}))
              )
        """, internal_ids * 4).fetchall()

        extra_node_ids = set()
        for r in cross_edges:
            if r["source_id"] not in internal_ids:
                extra_node_ids.add(r["source_id"])
            if r["target_id"] not in internal_ids:
                extra_node_ids.add(r["target_id"])

        if extra_node_ids:
            eids = list(extra_node_ids)
            eph = _placeholders(eids)
            extra_rows = conn.execute(
                f"SELECT id, type, props FROM nodes WHERE id IN ({eph})", eids
            ).fetchall()
            nodes += [_row_to_node(r) for r in extra_rows]

        all_edges = [
            {"source_id": r["source_id"], "rel_type": r["rel_type"],
             "target_id": r["target_id"], **json.loads(r["props"])}
            for r in list(internal_edges) + list(cross_edges)
        ]
        return {"nodes": nodes, "edges": all_edges, "warnings": []}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: symbol lookup
# ---------------------------------------------------------------------------

# What it does: Finds a class, function, or method by name and returns it with everything directly connected to it.
# Input: repo path, exact symbol name, and optionally the type (Class/Function/Method).
# Output: the matching node(s) and all their immediate neighbours and edges.
def read_symbol(repo_path: str, symbol_name: str, symbol_type: str | None = None) -> dict:
    conn = _connect(repo_path)
    try:
        type_clause = f"AND type = '{symbol_type}'" if symbol_type else ""
        root_rows = conn.execute(
            f"SELECT id, type, props FROM nodes "
            f"WHERE json_extract(props,'$.name')=? {type_clause}",
            (symbol_name,),
        ).fetchall()

        if not root_rows:
            return {"error": f"Symbol '{symbol_name}' not found."}

        root_ids = [r["id"] for r in root_rows]
        nodes = [_row_to_node(r) for r in root_rows]
        seen = set(root_ids)
        edges = []

        ph = _placeholders(root_ids)
        for r in conn.execute(f"""
            SELECT source_id, rel_type, target_id, props, target_id AS nb_id
            FROM edges WHERE source_id IN ({ph})
            UNION ALL
            SELECT source_id, rel_type, target_id, props, source_id AS nb_id
            FROM edges WHERE target_id IN ({ph})
        """, root_ids + root_ids):
            edges.append({
                "source_id": r["source_id"], "rel_type": r["rel_type"],
                "target_id": r["target_id"], **json.loads(r["props"]),
            })
            nb_id = r["nb_id"]
            if nb_id not in seen:
                seen.add(nb_id)
                nb = conn.execute(
                    "SELECT id, type, props FROM nodes WHERE id=?", (nb_id,)
                ).fetchone()
                if nb:
                    nodes.append(_row_to_node(nb))

        return {"nodes": nodes, "edges": edges, "warnings": []}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: call chain
# ---------------------------------------------------------------------------

# What it does: Traces who calls a function or what it calls, up to N hops.
# Input: repo path, function name, direction (callers/callees/both), and max depth.
# Output: all functions in the call chain with the edges connecting them.
def read_call_chain(
    repo_path: str,
    symbol_name: str,
    direction: str = "both",
    depth: int = 3,
) -> dict:
    depth = min(max(depth, 1), 10)
    conn = _connect(repo_path)
    try:
        start_rows = conn.execute(
            "SELECT id, type, props FROM nodes "
            "WHERE type IN ('Function','Method') AND json_extract(props,'$.name')=?",
            (symbol_name,),
        ).fetchall()
        if not start_rows:
            return {"error": f"No Function/Method named '{symbol_name}' found."}

        start_ids = [r["id"] for r in start_rows]
        nodes = [_row_to_node(r) for r in start_rows]
        seen = set(start_ids)
        edges: list[dict] = []

        def _traverse(source_col: str, target_col: str, seed_ids: list[str]) -> None:
            frontier = seed_ids[:]
            for _ in range(depth):
                if not frontier:
                    break
                ph = _placeholders(frontier)
                rows = conn.execute(
                    f"SELECT source_id, rel_type, target_id, props "
                    f"FROM edges WHERE rel_type='CALLS' AND {source_col} IN ({ph})",
                    frontier,
                ).fetchall()
                frontier = []
                for r in rows:
                    e = {"source_id": r["source_id"], "rel_type": r["rel_type"],
                         "target_id": r["target_id"], **json.loads(r["props"])}
                    if e not in edges:
                        edges.append(e)
                    nb_id = r[target_col]
                    if nb_id not in seen:
                        seen.add(nb_id)
                        frontier.append(nb_id)
                        nb = conn.execute(
                            "SELECT id, type, props FROM nodes WHERE id=?", (nb_id,)
                        ).fetchone()
                        if nb:
                            nodes.append(_row_to_node(nb))

        if direction in ("callees", "both"):
            _traverse("source_id", "target_id", start_ids)
        if direction in ("callers", "both"):
            _traverse("target_id", "source_id", start_ids)

        return {"nodes": nodes, "edges": edges, "warnings": []}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: blast radius
# ---------------------------------------------------------------------------

# What it does: Given changed files, finds every function and file that could break because it calls into the changed code.
# Input: repo path, list of changed file paths, and how many hops to follow.
# Output: changed symbols, affected symbols, affected files, and counts of each.
def read_blast_radius(
    repo_path: str,
    changed_file_paths: list[str],
    depth: int = 3,
) -> dict:
    depth = min(max(depth, 1), 10)
    conn = _connect(repo_path)
    try:
        if not changed_file_paths:
            return _blast_empty(repo_path, [], "No changed files provided.")

        # Resolve file nodes
        ph = _placeholders(changed_file_paths)
        file_rows = conn.execute(
            f"SELECT id, json_extract(props,'$.path') AS path FROM nodes "
            f"WHERE type='File' AND json_extract(props,'$.path') IN ({ph})",
            changed_file_paths,
        ).fetchall()

        found_paths = {r["path"] for r in file_rows}
        missing = [p for p in changed_file_paths if p not in found_paths]
        file_ids = [r["id"] for r in file_rows]
        warnings = [f"Files not in graph (run build first?): {missing}"] if missing else []

        if not file_ids:
            return _blast_empty(repo_path, changed_file_paths,
                                warnings[0] if warnings else "No file nodes found.")

        # Symbols in changed files — use placeholder-based IN clause
        fph = _placeholders(file_ids)
        changed_sym_rows = conn.execute(f"""
            WITH RECURSIVE defined(id) AS (
                SELECT id FROM nodes WHERE id IN ({fph})
                UNION ALL
                SELECT e.target_id FROM edges e
                JOIN defined d ON e.source_id = d.id
                WHERE e.rel_type IN ('DEFINES','CONTAINS')
            )
            SELECT n.id, n.type, n.props FROM nodes n
            JOIN defined d ON n.id = d.id
            WHERE n.type IN ('Function','Method','Class')
        """, file_ids).fetchall()

        changed_syms = [_sym_row(r) for r in changed_sym_rows]
        changed_sym_ids = [s["id"] for s in changed_syms]

        if not changed_sym_ids:
            warnings.append("Changed files contain no tracked symbols.")
            return {
                "repo_path": repo_path,
                "changed_files": sorted(found_paths),
                "changed_symbols": [],
                "affected_symbols": [],
                "affected_files": [],
                "total_changed_symbols": 0,
                "total_affected_symbols": 0,
                "total_affected_files": 0,
                "warnings": warnings,
            }

        # Callers via BFS up to depth
        affected_ids: set[str] = set()
        frontier = changed_sym_ids[:]
        for _ in range(depth):
            if not frontier:
                break
            ph2 = _placeholders(frontier)
            caller_rows = conn.execute(
                f"SELECT DISTINCT source_id FROM edges "
                f"WHERE rel_type='CALLS' AND target_id IN ({ph2})",
                frontier,
            ).fetchall()
            frontier = []
            for r in caller_rows:
                cid = r["source_id"]
                if cid not in affected_ids and cid not in set(changed_sym_ids):
                    affected_ids.add(cid)
                    frontier.append(cid)

        affected_syms: list[dict] = []
        if affected_ids:
            aph = _placeholders(list(affected_ids))
            affected_rows = conn.execute(
                f"SELECT id, type, props FROM nodes WHERE id IN ({aph})",
                list(affected_ids),
            ).fetchall()
            affected_syms = [_sym_row(r) for r in affected_rows]

        affected_files = sorted({s["file_path"] for s in affected_syms if s.get("file_path")})

        return {
            "repo_path": repo_path,
            "changed_files": sorted(found_paths),
            "changed_symbols": changed_syms,
            "affected_symbols": affected_syms,
            "affected_files": affected_files,
            "total_changed_symbols": len(changed_syms),
            "total_affected_symbols": len(affected_syms),
            "total_affected_files": len(affected_files),
            "warnings": warnings,
        }
    finally:
        conn.close()


def _sym_row(r: sqlite3.Row) -> dict:
    props = json.loads(r["props"])
    return {
        "id": r["id"],
        "type": r["type"],
        "name": props.get("name"),
        "qualname": props.get("qualname"),
        "file_path": props.get("file_path"),
    }


def _blast_empty(repo_path: str, changed_files: list[str], warning: str) -> dict:
    return {
        "repo_path": repo_path,
        "changed_files": changed_files,
        "changed_symbols": [],
        "affected_symbols": [],
        "affected_files": [],
        "total_changed_symbols": 0,
        "total_affected_symbols": 0,
        "total_affected_files": 0,
        "warnings": [warning] if warning else [],
    }

# ---------------------------------------------------------------------------
# Read: minimal context (~100 tokens)
# ---------------------------------------------------------------------------

# What it does: Returns the smallest useful summary of the graph — just enough for an agent to orient itself.
# Input: repo path.
# Output: node/edge counts, top-level folders, and the 5 most-connected files.
def read_minimal_context(repo_path: str) -> dict:
    """
    Ultra-compact graph summary for agent orientation.
    Returns enough signal to decide what to query next — in ~100 tokens.
    """
    conn = _connect(repo_path)
    try:
        # Node counts
        node_counts: dict[str, int] = {}
        for row in conn.execute("SELECT type, COUNT(*) AS cnt FROM nodes GROUP BY type"):
            node_counts[row["type"]] = row["cnt"]

        # Edge counts
        edge_counts: dict[str, int] = {}
        for row in conn.execute("SELECT rel_type, COUNT(*) AS cnt FROM edges GROUP BY rel_type"):
            edge_counts[row["rel_type"]] = row["cnt"]

        # Repo info
        repo_row = conn.execute(
            "SELECT props FROM nodes WHERE type='Repository' LIMIT 1"
        ).fetchone()
        repo_props = json.loads(repo_row["props"]) if repo_row else {}

        # Top-level folders (direct children of Repository only)
        repo_id_row = conn.execute(
            "SELECT id FROM nodes WHERE type='Repository' LIMIT 1"
        ).fetchone()
        folders = []
        if repo_id_row:
            folders = [
                json.loads(r["props"]).get("path")
                for r in conn.execute(
                    """
                    SELECT n.props FROM edges e
                    JOIN nodes n ON n.id = e.target_id AND n.type = 'Folder'
                    WHERE e.rel_type = 'CONTAINS' AND e.source_id = ?
                    """,
                    (repo_id_row["id"],),
                ).fetchall()
            ]

        # Most connected files (by edge count — hotspots)
        hotspots = [
            json.loads(r["props"]).get("path")
            for r in conn.execute(
                """
                SELECT n.props, COUNT(*) AS degree
                FROM edges e JOIN nodes n ON n.id = e.source_id OR n.id = e.target_id
                WHERE n.type = 'File'
                GROUP BY n.id ORDER BY degree DESC LIMIT 5
                """
            ).fetchall()
        ]

        return {
            "repo": repo_props.get("name"),
            "path": repo_props.get("path"),
            "nodes": node_counts,
            "edges": edge_counts,
            "folders": folders,
            "hotspot_files": hotspots,
            "db": str(db_path(repo_path)),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: hub nodes — most connected symbols
# ---------------------------------------------------------------------------

# What it does: Finds the most connected symbols in the codebase ranked by total connections.
# Input: repo path, how many results you want, and which node types to include.
# Output: ranked list of symbols with inbound, outbound, and total connection counts.
# Why it matters: high connection count = high risk if that symbol changes.
def read_hub_nodes(repo_path: str, top_n: int = 10, node_types: list[str] | None = None) -> list[dict]:
    """
    Return the top N most-connected nodes (classes, functions, methods).

    A node's connection count is the total of:
    - outbound edges (things it calls / defines / imports)
    - inbound edges  (things that call / use it)

    High connection count = high blast radius if changed.
    """
    types = node_types or ["Function", "Method", "Class"]
    placeholders = ",".join(f"'{t}'" for t in types)

    conn = _connect(repo_path)
    try:
        rows = conn.execute(f"""
            SELECT
                n.id,
                json_extract(n.props, '$.name')      AS name,
                json_extract(n.props, '$.qualname')  AS qualname,
                json_extract(n.props, '$.file_path') AS file_path,
                n.type,
                COUNT(DISTINCT e1.rowid) AS outbound,
                COUNT(DISTINCT e2.rowid) AS inbound,
                COUNT(DISTINCT e1.rowid) + COUNT(DISTINCT e2.rowid) AS total
            FROM nodes n
            LEFT JOIN edges e1 ON e1.source_id = n.id
            LEFT JOIN edges e2 ON e2.target_id = n.id
            WHERE n.type IN ({placeholders})
            GROUP BY n.id
            ORDER BY total DESC
            LIMIT ?
        """, (top_n,)).fetchall()

        return [
            {
                "name":      row["name"],
                "qualname":  row["qualname"],
                "type":      row["type"],
                "file_path": row["file_path"],
                "inbound":   row["inbound"],
                "outbound":  row["outbound"],
                "total":     row["total"],
            }
            for row in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: large functions — functions exceeding a line count threshold
# ---------------------------------------------------------------------------

# What it does: Finds functions and methods that are longer than a given number of lines.
# Input: repo path, minimum number of lines to flag (default 50), and which types to check.
# Output: a list of oversized symbols sorted from largest to smallest, with file and line info.
# Why it matters: large functions are harder to test, review, and maintain.
def read_large_functions(
    repo_path: str,
    min_lines: int = 50,
    node_types: list[str] | None = None,
) -> list[dict]:
    types = node_types or ["Function", "Method"]
    placeholders = ",".join(f"'{t}'" for t in types)

    conn = _connect(repo_path)
    try:
        rows = conn.execute(f"""
            SELECT
                json_extract(props, '$.name')      AS name,
                json_extract(props, '$.qualname')  AS qualname,
                json_extract(props, '$.file_path') AS file_path,
                json_extract(props, '$.lineno')    AS line_start,
                json_extract(props, '$.line_end')  AS line_end,
                json_extract(props, '$.line_end') - json_extract(props, '$.lineno') AS size,
                type
            FROM nodes
            WHERE type IN ({placeholders})
              AND json_extract(props, '$.line_end') IS NOT NULL
              AND (json_extract(props, '$.line_end') - json_extract(props, '$.lineno')) >= ?
            ORDER BY size DESC
        """, (min_lines,)).fetchall()

        return [
            {
                "name":       row["name"],
                "qualname":   row["qualname"],
                "type":       row["type"],
                "file_path":  row["file_path"],
                "line_start": row["line_start"],
                "line_end":   row["line_end"],
                "size":       row["size"],
            }
            for row in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: traverse graph — BFS from any node following any edge types
# ---------------------------------------------------------------------------

# What it does: Starts from a named node and walks outward through the graph,
# following the edge types you choose, up to a set number of hops.
# Input: repo path, starting node name, which edge types to follow,
#        direction (out/in/both), and max depth.
# Output: all nodes and edges reachable from the start within the given depth.
# Why it matters: more flexible than query_call_chain — works across any edge type,
#                 not just CALLS.
def read_traverse(
    repo_path: str,
    start: str,
    edge_types: list[str] | None = None,
    direction: str = "out",
    depth: int = 2,
) -> dict:
    depth = min(max(depth, 1), 5)
    edges_to_follow = edge_types or ["CALLS", "DEFINES", "IMPORTS", "EXTENDS"]
    et_clause = ",".join(f"'{e}'" for e in edges_to_follow)

    conn = _connect(repo_path)
    try:
        # Find the starting node by name
        start_row = conn.execute(
            "SELECT id, type, props FROM nodes WHERE json_extract(props, '$.name') = ? LIMIT 1",
            (start,),
        ).fetchone()

        if not start_row:
            return {"error": f"No node named '{start}' found in the graph."}

        start_node = _row_to_node(start_row)
        visited: set[str] = {start_row["id"]}
        frontier: list[str] = [start_row["id"]]
        all_nodes: list[dict] = [start_node]
        all_edges: list[dict] = []

        for _ in range(depth):
            if not frontier:
                break

            ph = _placeholders(frontier)

            # Outbound: nodes this frontier points to
            if direction in ("out", "both"):
                rows = conn.execute(f"""
                    SELECT e.source_id, e.rel_type, e.target_id, e.props,
                           n.id, n.type, n.props AS nprops
                    FROM edges e JOIN nodes n ON n.id = e.target_id
                    WHERE e.source_id IN ({ph}) AND e.rel_type IN ({et_clause})
                """, frontier).fetchall()
                for r in rows:
                    all_edges.append({
                        "source_id": r["source_id"],
                        "rel_type":  r["rel_type"],
                        "target_id": r["target_id"],
                    })
                    if r["id"] not in visited:
                        visited.add(r["id"])
                        frontier.append(r["id"])
                        all_nodes.append(_row_to_node(
                            conn.execute("SELECT id, type, props FROM nodes WHERE id=?", (r["id"],)).fetchone()
                        ))

            # Inbound: nodes that point to this frontier
            if direction in ("in", "both"):
                rows = conn.execute(f"""
                    SELECT e.source_id, e.rel_type, e.target_id, e.props,
                           n.id, n.type, n.props AS nprops
                    FROM edges e JOIN nodes n ON n.id = e.source_id
                    WHERE e.target_id IN ({ph}) AND e.rel_type IN ({et_clause})
                """, frontier).fetchall()
                for r in rows:
                    all_edges.append({
                        "source_id": r["source_id"],
                        "rel_type":  r["rel_type"],
                        "target_id": r["target_id"],
                    })
                    if r["id"] not in visited:
                        visited.add(r["id"])
                        frontier.append(r["id"])
                        all_nodes.append(_row_to_node(
                            conn.execute("SELECT id, type, props FROM nodes WHERE id=?", (r["id"],)).fetchone()
                        ))

        return {
            "start": start,
            "edge_types": edges_to_follow,
            "direction": direction,
            "depth": depth,
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "nodes": all_nodes,
            "edges": all_edges,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Communities — Louvain community detection
# ---------------------------------------------------------------------------

# What it does: Loads the graph into networkx, runs Louvain community detection,
# and saves the results to the communities table in SQLite.
# Input: repo path.
# Output: summary dict with total nodes, edges, and number of communities found.
# Why it matters: reveals the natural architectural layers of the codebase —
#                 which files/functions cluster together vs. are isolated.
def build_communities(repo_path: str) -> dict:
    try:
        import networkx as nx
    except ImportError:
        return {"error": "networkx is not installed. Run: pip install networkx"}

    conn = _connect(repo_path)
    _bootstrap(conn)
    try:
        # Load symbol nodes only (not structural Repository/Folder nodes)
        node_rows = conn.execute(
            "SELECT id FROM nodes WHERE type IN ('File','Class','Function','Method')"
        ).fetchall()

        if not node_rows:
            return {"error": "No nodes found. Run build_python_code_ontology first."}

        node_ids = {r["id"] for r in node_rows}

        G = nx.Graph()
        G.add_nodes_from(node_ids)

        # Only meaningful semantic edges — skip structural CONTAINS
        edge_rows = conn.execute(
            "SELECT source_id, target_id FROM edges "
            "WHERE rel_type IN ('CALLS','DEFINES','IMPORTS','EXTENDS')"
        ).fetchall()
        for r in edge_rows:
            if r["source_id"] in node_ids and r["target_id"] in node_ids:
                G.add_edge(r["source_id"], r["target_id"])

        communities = nx.community.louvain_communities(G, seed=42)

        conn.execute("DELETE FROM communities")
        for comm_id, node_set in enumerate(communities):
            conn.executemany(
                "INSERT OR REPLACE INTO communities(node_id, community_id) VALUES (?, ?)",
                [(nid, comm_id) for nid in node_set],
            )
        conn.commit()

        return {
            "status": "built",
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
            "total_communities": len(communities),
            "community_sizes": sorted([len(c) for c in communities], reverse=True),
        }
    finally:
        conn.close()


# What it does: Computes betweenness centrality for all symbol nodes and stores the top results.
# Input: repo path, and how many top bridge nodes to keep (default 50).
# Output: summary dict with node count and top scores.
def build_bridge_nodes(repo_path: str, top_n: int = 50) -> dict:
    try:
        import networkx as nx
    except ImportError:
        return {"error": "networkx is not installed. Run: pip install networkx"}

    conn = _connect(repo_path)
    _bootstrap(conn)
    try:
        node_rows = conn.execute(
            "SELECT id FROM nodes WHERE type IN ('File','Class','Function','Method')"
        ).fetchall()

        if not node_rows:
            return {"error": "No nodes found. Run build_python_code_ontology first."}

        node_ids = {r["id"] for r in node_rows}

        G = nx.Graph()
        G.add_nodes_from(node_ids)

        edge_rows = conn.execute(
            "SELECT source_id, target_id FROM edges "
            "WHERE rel_type IN ('CALLS','DEFINES','IMPORTS','EXTENDS')"
        ).fetchall()
        for r in edge_rows:
            if r["source_id"] in node_ids and r["target_id"] in node_ids:
                G.add_edge(r["source_id"], r["target_id"])

        centrality = nx.betweenness_centrality(G, normalized=True)

        # Keep only top_n non-zero scores
        top = sorted(
            [(nid, score) for nid, score in centrality.items() if score > 0],
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

        conn.execute("DELETE FROM bridge_nodes")
        conn.executemany(
            "INSERT OR REPLACE INTO bridge_nodes(node_id, score) VALUES (?, ?)",
            top,
        )
        conn.commit()

        return {
            "status": "built",
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
            "bridge_nodes_found": len(top),
        }
    finally:
        conn.close()


# What it does: Reads community data from SQLite and returns a structured summary.
# Input: repo path, and how many communities to return (default 20, largest first).
# Output: list of communities, each with a label, size, top nodes, and the files they span.
def read_communities(repo_path: str, top_n: int = 20) -> dict:
    conn = _connect(repo_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM communities").fetchone()["cnt"]
        if count == 0:
            return {
                "error": "No communities built yet. Call list_communities to detect them first."
            }

        total_communities = conn.execute(
            "SELECT COUNT(DISTINCT community_id) AS cnt FROM communities"
        ).fetchone()["cnt"]

        size_rows = conn.execute("""
            SELECT community_id, COUNT(*) AS size
            FROM communities
            GROUP BY community_id
            ORDER BY size DESC
            LIMIT ?
        """, (top_n,)).fetchall()

        communities_out = []
        for row in size_rows:
            comm_id = row["community_id"]
            size = row["size"]

            # Top 5 nodes in this community ranked by degree
            top_node_rows = conn.execute("""
                SELECT n.id, n.type, n.props,
                       COUNT(DISTINCT e1.rowid) + COUNT(DISTINCT e2.rowid) AS degree
                FROM communities c
                JOIN nodes n ON n.id = c.node_id
                LEFT JOIN edges e1 ON e1.source_id = n.id
                LEFT JOIN edges e2 ON e2.target_id = n.id
                WHERE c.community_id = ?
                GROUP BY n.id
                ORDER BY degree DESC
                LIMIT 5
            """, (comm_id,)).fetchall()

            top_nodes = []
            label = f"community_{comm_id}"
            for i, n in enumerate(top_node_rows):
                props = json.loads(n["props"])
                name = props.get("name") or n["id"]
                if i == 0:
                    fp = props.get("file_path") or ""
                    if fp:
                        # Use the first path component as a short readable label
                        label = fp.split("/")[0] if "/" in fp else fp.removesuffix(".py")
                    else:
                        label = name
                top_nodes.append({
                    "name": name,
                    "type": n["type"],
                    "file_path": props.get("file_path"),
                    "degree": n["degree"],
                })

            # Distinct files that have symbols in this community
            file_rows = conn.execute("""
                SELECT DISTINCT json_extract(n.props, '$.file_path') AS fp
                FROM communities c
                JOIN nodes n ON n.id = c.node_id
                WHERE c.community_id = ?
                  AND json_extract(n.props, '$.file_path') IS NOT NULL
                LIMIT 15
            """, (comm_id,)).fetchall()
            files = [r["fp"] for r in file_rows if r["fp"]]

            communities_out.append({
                "community_id": comm_id,
                "label": label,
                "size": size,
                "top_nodes": top_nodes,
                "files": files,
            })

        return {
            "total_communities": total_communities,
            "showing": len(communities_out),
            "communities": communities_out,
        }
    finally:
        conn.close()


# What it does: Reads bridge node scores from SQLite and returns a ranked list.
# Input: repo path, and how many top bridge nodes to return (default 20).
# Output: list of nodes ranked by betweenness centrality score, with name/type/file.
def read_bridge_nodes(repo_path: str, top_n: int = 20) -> dict:
    conn = _connect(repo_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM bridge_nodes").fetchone()["cnt"]
        if count == 0:
            return {
                "error": "No bridge nodes built yet. Call get_bridge_nodes to compute them first."
            }

        rows = conn.execute("""
            SELECT b.node_id, b.score, n.type, n.props
            FROM bridge_nodes b
            JOIN nodes n ON n.id = b.node_id
            ORDER BY b.score DESC
            LIMIT ?
        """, (top_n,)).fetchall()

        nodes_out = []
        for r in rows:
            props = json.loads(r["props"])
            nodes_out.append({
                "name": props.get("name") or r["node_id"],
                "type": r["type"],
                "file_path": props.get("file_path"),
                "betweenness_score": round(r["score"], 4),
            })

        return {
            "total_bridge_nodes": count,
            "showing": len(nodes_out),
            "bridge_nodes": nodes_out,
        }
    finally:
        conn.close()


# What it does: Detects isolated nodes and untested hotspots, persists to knowledge_gaps table.
# Input: repo path, degree threshold above which a hub node is considered a hotspot (default 5).
# Output: summary dict with counts of each gap type found.
def build_knowledge_gaps(repo_path: str, hotspot_degree: int = 5) -> dict:
    conn = _connect(repo_path)
    _bootstrap(conn)
    try:
        node_rows = conn.execute(
            "SELECT id, type, props FROM nodes WHERE type IN ('File','Class','Function','Method')"
        ).fetchall()

        if not node_rows:
            return {"error": "No nodes found. Run build_python_code_ontology first."}

        conn.execute("DELETE FROM knowledge_gaps")
        gaps = []

        for r in node_rows:
            node_id = r["id"]
            props = json.loads(r["props"])
            name = props.get("name") or node_id
            file_path = props.get("file_path")

            degree = conn.execute("""
                SELECT COUNT(*) AS cnt FROM edges
                WHERE source_id = ? OR target_id = ?
            """, (node_id, node_id)).fetchone()["cnt"]

            # Gap type 1: isolated — no edges at all
            if degree == 0:
                gaps.append((
                    node_id,
                    "isolated",
                    json.dumps({"name": name, "type": r["type"], "file_path": file_path}),
                ))
                continue

            # Gap type 2: untested hotspot — high degree but no test_* callers
            if degree >= hotspot_degree:
                test_callers = conn.execute("""
                    SELECT COUNT(*) AS cnt FROM edges e
                    JOIN nodes n ON n.id = e.source_id
                    WHERE e.target_id = ?
                      AND e.rel_type = 'CALLS'
                      AND (
                        json_extract(n.props, '$.name') LIKE 'test_%'
                        OR json_extract(n.props, '$.file_path') LIKE '%test%'
                      )
                """, (node_id,)).fetchone()["cnt"]

                if test_callers == 0:
                    gaps.append((
                        node_id,
                        "untested_hotspot",
                        json.dumps({
                            "name": name,
                            "type": r["type"],
                            "file_path": file_path,
                            "degree": degree,
                        }),
                    ))

        conn.executemany(
            "INSERT OR REPLACE INTO knowledge_gaps(node_id, gap_type, detail) VALUES (?, ?, ?)",
            gaps,
        )
        conn.commit()

        isolated_count = sum(1 for g in gaps if g[1] == "isolated")
        hotspot_count = sum(1 for g in gaps if g[1] == "untested_hotspot")

        return {
            "status": "built",
            "total_nodes_scanned": len(node_rows),
            "isolated": isolated_count,
            "untested_hotspots": hotspot_count,
            "total_gaps": len(gaps),
        }
    finally:
        conn.close()


# What it does: Reads knowledge gaps from SQLite and returns them grouped by type.
# Input: repo path, optional filters for gap types to include.
# Output: dict with isolated nodes and untested hotspots lists.
def read_knowledge_gaps(repo_path: str) -> dict:
    conn = _connect(repo_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_gaps").fetchone()["cnt"]
        if count == 0:
            return {
                "error": "No knowledge gaps built yet. Call get_knowledge_gaps to compute them first."
            }

        rows = conn.execute("""
            SELECT node_id, gap_type, detail
            FROM knowledge_gaps
            ORDER BY gap_type, node_id
        """).fetchall()

        isolated = []
        untested_hotspots = []

        for r in rows:
            detail = json.loads(r["detail"])
            if r["gap_type"] == "isolated":
                isolated.append(detail)
            elif r["gap_type"] == "untested_hotspot":
                untested_hotspots.append(detail)

        # Sort hotspots by degree descending
        untested_hotspots.sort(key=lambda x: x.get("degree", 0), reverse=True)

        return {
            "total_gaps": count,
            "isolated": {
                "count": len(isolated),
                "nodes": isolated,
            },
            "untested_hotspots": {
                "count": len(untested_hotspots),
                "nodes": untested_hotspots,
            },
        }
    finally:
        conn.close()


# What it does: Detects entry points (0 inbound CALLS) and BFS-traces each call path.
# Input: repo path, max BFS depth (default 5), max entry points to trace (default 20).
# Output: summary dict with counts of entry points and flows stored.
def build_flows(repo_path: str, max_depth: int = 5, max_entries: int = 20) -> dict:
    conn = _connect(repo_path)
    _bootstrap(conn)
    try:
        # Only trace Function and Method nodes
        node_rows = conn.execute(
            "SELECT id, props FROM nodes WHERE type IN ('Function', 'Method')"
        ).fetchall()

        if not node_rows:
            return {"error": "No nodes found. Run build_python_code_ontology first."}

        all_fn_ids = {r["id"] for r in node_rows}
        props_map = {r["id"]: json.loads(r["props"]) for r in node_rows}

        # Build adjacency: caller → [callees]
        call_rows = conn.execute(
            "SELECT source_id, target_id FROM edges WHERE rel_type = 'CALLS'"
        ).fetchall()

        callees: dict[str, list[str]] = {nid: [] for nid in all_fn_ids}
        inbound: dict[str, int] = {nid: 0 for nid in all_fn_ids}

        for r in call_rows:
            src, dst = r["source_id"], r["target_id"]
            if src in all_fn_ids and dst in all_fn_ids:
                callees[src].append(dst)
                inbound[dst] = inbound.get(dst, 0) + 1

        # Entry points: functions with 0 inbound CALLS edges
        # Sort by outbound call count descending so interesting flows come first
        entries = sorted(
            [nid for nid in all_fn_ids if inbound.get(nid, 0) == 0],
            key=lambda nid: len(callees.get(nid, [])),
            reverse=True,
        )[:max_entries]

        conn.execute("DELETE FROM flows")
        stored = 0

        for entry_id in entries:
            # BFS
            path_nodes = []
            visited = set()
            queue = [(entry_id, 0)]

            while queue:
                cur_id, depth = queue.pop(0)
                if cur_id in visited or depth > max_depth:
                    continue
                visited.add(cur_id)
                p = props_map.get(cur_id, {})
                path_nodes.append({
                    "id": cur_id,
                    "name": p.get("name", cur_id),
                    "file_path": p.get("file_path"),
                    "depth": depth,
                })
                for callee_id in callees.get(cur_id, []):
                    if callee_id not in visited:
                        queue.append((callee_id, depth + 1))

            conn.execute(
                "INSERT OR REPLACE INTO flows(entry_id, path) VALUES (?, ?)",
                (entry_id, json.dumps(path_nodes)),
            )
            stored += 1

        conn.commit()

        return {
            "status": "built",
            "total_functions": len(all_fn_ids),
            "entry_points_found": len(entries),
            "flows_stored": stored,
        }
    finally:
        conn.close()


# What it does: Reads stored flows from SQLite and returns them as a list.
# Input: repo path, max flows to return (default 20).
# Output: list of flows, each with an entry point and its BFS call path.
def read_flows(repo_path: str, top_n: int = 20) -> dict:
    conn = _connect(repo_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM flows").fetchone()["cnt"]
        if count == 0:
            return {"error": "No flows built yet. Call list_flows to compute them first."}

        rows = conn.execute("""
            SELECT f.entry_id, f.path, n.props
            FROM flows f
            JOIN nodes n ON n.id = f.entry_id
            ORDER BY json_array_length(f.path) DESC
            LIMIT ?
        """, (top_n,)).fetchall()

        flows_out = []
        for r in rows:
            props = json.loads(r["props"])
            path = json.loads(r["path"])
            flows_out.append({
                "entry_point": {
                    "name": props.get("name", r["entry_id"]),
                    "file_path": props.get("file_path"),
                },
                "path_length": len(path),
                "path": path,
            })

        return {
            "total_flows": count,
            "showing": len(flows_out),
            "flows": flows_out,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Symbol resolution — context-aware disambiguation
# ---------------------------------------------------------------------------

# What it does: Given a symbol name and the file the agent is currently working in,
# returns the most relevant match using the import chain.
# Input: repo path, symbol name, current file (repo-relative path), optional type filter.
# Output: ranked list of candidates — import-resolved match first, then same-community, then rest.
def resolve_symbol(
    repo_path: str,
    symbol_name: str,
    current_file: str,
    symbol_type: str | None = None,
) -> dict:
    conn = _connect(repo_path)
    try:
        # Find all nodes matching the symbol name
        type_filter = ""
        params: list = [symbol_name]
        if symbol_type:
            type_filter = "AND n.type = ?"
            params.append(symbol_type)

        candidates = conn.execute(f"""
            SELECT n.id, n.type, n.props
            FROM nodes n
            WHERE json_extract(n.props, '$.name') = ?
              AND n.type IN ('Function', 'Method', 'Class')
              {type_filter}
        """, params).fetchall()

        if not candidates:
            return {"symbol_name": symbol_name, "candidates": [], "resolved": None}

        if len(candidates) == 1:
            props = json.loads(candidates[0]["props"])
            return {
                "symbol_name": symbol_name,
                "resolved": {
                    "name": props.get("name"),
                    "type": candidates[0]["type"],
                    "file_path": props.get("file_path"),
                    "qualname": props.get("qualname"),
                    "lineno": props.get("lineno"),
                    "confidence": "only_match",
                },
                "candidates": [],
            }

        # Find files that current_file imports (direct IMPORTS edges)
        imported_files = set()
        current_file_row = conn.execute("""
            SELECT n.id FROM nodes n
            WHERE n.type = 'File'
              AND json_extract(n.props, '$.path') = ?
        """, (current_file,)).fetchone()

        if current_file_row:
            imp_rows = conn.execute("""
                SELECT json_extract(n.props, '$.path') AS path
                FROM edges e
                JOIN nodes n ON n.id = e.target_id
                WHERE e.source_id = ?
                  AND e.rel_type = 'IMPORTS'
                  AND n.type = 'File'
            """, (current_file_row["id"],)).fetchall()
            imported_files = {r["path"] for r in imp_rows if r["path"]}

        # Find community of current file
        current_community = None
        if current_file_row:
            comm_row = conn.execute("""
                SELECT community_id FROM communities WHERE node_id = ?
            """, (current_file_row["id"],)).fetchone()
            if comm_row:
                current_community = comm_row["community_id"]

        # Rank candidates
        ranked = []
        for c in candidates:
            props = json.loads(c["props"])
            file_path = props.get("file_path") or ""

            # Check community match
            comm_row = conn.execute(
                "SELECT community_id FROM communities WHERE node_id = ?", (c["id"],)
            ).fetchone()
            candidate_community = comm_row["community_id"] if comm_row else None

            # Determine confidence
            if file_path == current_file:
                confidence = "same_file"
                rank = 0
            elif file_path in imported_files:
                confidence = "import_resolved"
                rank = 1
            elif candidate_community is not None and candidate_community == current_community:
                confidence = "same_community"
                rank = 2
            else:
                confidence = "other"
                rank = 3

            ranked.append({
                "rank": rank,
                "name": props.get("name"),
                "type": c["type"],
                "file_path": file_path,
                "qualname": props.get("qualname"),
                "lineno": props.get("lineno"),
                "confidence": confidence,
            })

        ranked.sort(key=lambda x: x["rank"])
        for r in ranked:
            del r["rank"]

        return {
            "symbol_name": symbol_name,
            "current_file": current_file,
            "resolved": ranked[0],
            "candidates": ranked[1:],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# File hashes — used for incremental builds
# ---------------------------------------------------------------------------

# What it does: Returns all stored file hashes from the last build.
# Input: repo path.
# Output: a dict mapping repo-relative file path → its SHA-256 hash.
def read_file_hashes(repo_path: str) -> dict[str, str]:
    if not db_path(repo_path).exists():
        return {}
    conn = _connect(repo_path)
    try:
        rows = conn.execute("SELECT path, hash FROM file_hashes").fetchall()
        return {r["path"]: r["hash"] for r in rows}
    finally:
        conn.close()


# What it does: Saves file hashes into the database after a build,
# so the next build can compare and skip unchanged files.
# Input: repo path, and a dict mapping file paths to their hashes.
# Output: nothing — saves as a side effect.
def write_file_hashes(repo_path: str, hashes: dict[str, str]) -> None:
    conn = _connect(repo_path)
    _bootstrap(conn)
    try:
        for path, hash_val in hashes.items():
            conn.execute(
                "INSERT OR REPLACE INTO file_hashes(path, hash) VALUES (?, ?)",
                (path, hash_val),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read: detect changes — risk-scored impact report for changed files
# ---------------------------------------------------------------------------

# What it does: Given a list of changed files, returns every affected symbol
# with a risk score, dependent count, and whether it has test coverage.
# Risk score is 0.0 (low risk) to 1.0 (high risk).
# Input: repo path, list of changed file paths, and traversal depth.
# Output: prioritised list of symbols to review, sorted by risk score.
def read_detect_changes(
    repo_path: str,
    changed_file_paths: list[str],
    depth: int = 3,
) -> dict:
    if not changed_file_paths:
        return {
            "changed_files": [],
            "report": [],
            "total_symbols": 0,
            "warnings": ["No changed files provided."],
        }

    # Step 1: get blast radius to find changed + affected symbols
    blast = read_blast_radius(repo_path, changed_file_paths, depth)

    all_symbols = blast["changed_symbols"] + blast["affected_symbols"]
    if not all_symbols:
        return {
            "changed_files": blast["changed_files"],
            "report": [],
            "total_symbols": 0,
            "warnings": blast.get("warnings", []),
        }

    sym_ids = [s["id"] for s in all_symbols]
    ph = _placeholders(sym_ids)

    conn = _connect(repo_path)
    try:
        # For each symbol: count dependents + check test coverage
        rows = conn.execute(f"""
            SELECT
                n.id,
                COUNT(DISTINCT callers.source_id) AS dependent_count,
                SUM(CASE WHEN json_extract(caller_node.props, '$.name') LIKE 'test_%'
                    THEN 1 ELSE 0 END) AS test_count
            FROM nodes n
            LEFT JOIN edges callers     ON callers.target_id = n.id AND callers.rel_type = 'CALLS'
            LEFT JOIN nodes caller_node ON caller_node.id = callers.source_id
            WHERE n.id IN ({ph})
            GROUP BY n.id
        """, sym_ids).fetchall()

        # Build lookup by id
        stats = {r["id"]: r for r in rows}

        report = []
        for sym in all_symbols:
            s = stats.get(sym["id"])
            dependent_count = s["dependent_count"] if s else 0
            has_test = (s["test_count"] > 0) if s else False
            is_changed = sym in blast["changed_symbols"]

            # Risk = dependents / 5 capped at 0.7, plus 0.3 if no test coverage
            risk = min(1.0, round(
                min(dependent_count / 5, 0.7) + (0.3 if not has_test else 0.0),
                2
            ))

            report.append({
                "name":            sym["name"],
                "qualname":        sym["qualname"],
                "type":            sym["type"],
                "file_path":       sym["file_path"],
                "changed_directly": is_changed,
                "dependent_count": dependent_count,
                "has_test":        has_test,
                "risk_score":      risk,
            })

        # Sort by risk score descending
        report.sort(key=lambda x: x["risk_score"], reverse=True)

        return {
            "changed_files":  blast["changed_files"],
            "total_symbols":  len(report),
            "report":         report,
            "warnings":       blast.get("warnings", []),
        }
    finally:
        conn.close()

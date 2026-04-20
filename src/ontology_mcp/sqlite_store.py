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

def db_path(repo_path: str) -> Path:
    return Path(repo_path).resolve() / DB_DIR / DB_FILE


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
        CREATE INDEX IF NOT EXISTS idx_edges_source  ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target  ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_rel     ON edges(rel_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_type    ON nodes(type);
    """)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

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

def _row_to_node(row: sqlite3.Row) -> dict:
    props = json.loads(row["props"])
    return {"id": row["id"], "type": row["type"], **props}


def _ids_from(rows: list[sqlite3.Row]) -> list[str]:
    return [r["id"] for r in rows]


def _placeholders(ids: list[str]) -> str:
    return ",".join("?" * len(ids))


# ---------------------------------------------------------------------------
# Read: existence check
# ---------------------------------------------------------------------------

def graph_exists(repo_path: str) -> bool:
    return db_path(repo_path).exists()


# ---------------------------------------------------------------------------
# Read: overview
# ---------------------------------------------------------------------------

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

        # Symbols in changed files
        fph = _placeholders(file_ids)
        changed_sym_rows = conn.execute(f"""
            WITH RECURSIVE defined(id) AS (
                SELECT unnested.id FROM (VALUES {','.join(f'({repr(i)})' for i in file_ids)}) AS unnested(id)
                UNION ALL
                SELECT e.target_id FROM edges e
                JOIN defined d ON e.source_id = d.id
                WHERE e.rel_type IN ('DEFINES','CONTAINS')
            )
            SELECT n.id, n.type, n.props FROM nodes n
            JOIN defined d ON n.id = d.id
            WHERE n.type IN ('Function','Method','Class')
        """).fetchall()

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

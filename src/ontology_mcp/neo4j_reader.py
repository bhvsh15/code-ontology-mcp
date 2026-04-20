from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ontology_mcp.neo4j_writer import Neo4jConfig, load_neo4j_config  # reuse config

# Models for Neo4j query results
@dataclass
class NodeRecord:
    id: str
    type: str
    properties: dict[str, Any]


@dataclass
class EdgeRecord:
    source_id: str
    rel_type: str
    target_id: str
    properties: dict[str, Any]


@dataclass
class GraphSlice:
    """A partial or full view of the graph returned by a query."""
    nodes: list[NodeRecord]
    edges: list[EdgeRecord]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

# Helper to convert a neo4j Record with a single node binding 'n' to a NodeRecord
def _node_from_record(record: Any) -> NodeRecord:
    """Convert a neo4j Record with a single node binding 'n' to a NodeRecord."""
    n = record["n"]
    labels = list(n.labels)
    node_type = labels[0] if labels else "Unknown"
    return NodeRecord(id=n["id"], type=node_type, properties=dict(n))


# Helper to run a query and collect results into NodeRecord 
def _run_and_collect_nodes(session: Any, query: str, **params: Any) -> list[NodeRecord]:
    result = session.run(query, **params)
    return [_node_from_record(r) for r in result]


# Helper to run a query and collect results into EdgeRecord
def _run_and_collect_edges(session: Any, query: str, **params: Any) -> list[EdgeRecord]:
    result = session.run(query, **params)
    edges = []
    for r in result:
        rel = r["r"]
        edges.append(EdgeRecord(
            source_id=r["source_id"],
            rel_type=rel.type,
            target_id=r["target_id"],
            properties=dict(rel),
        ))
    return edges


# Helper to open a Neo4j session using the provided config
def _open_session(config: Neo4jConfig):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(config.uri, auth=(config.username, config.password))
    return driver, driver.session(database=config.database)


#----------------------------------------------------------------------------
# Check whether a repo graph exists in Neo4j
#---------------------------------------------------------------------------
def repo_exists_in_neo4j(repo_name: str, config: Neo4jConfig | None = None) -> bool:
    """Return True if a Repository node with this name exists in Neo4j."""
    cfg = config or load_neo4j_config()
    driver, session = _open_session(cfg)
    try:
        result = session.run(
            "MATCH (r:Repository {name: $name}) RETURN count(r) AS cnt",
            name=repo_name,
        )
        #.single() returns a Record or None
        return result.single()["cnt"] > 0
    finally:
        session.close()
        driver.close()

# ---------------------------------------------------------------------------
# Query: full graph overview for a repo
# ---------------------------------------------------------------------------
def read_graph_overview(repo_name: str, config: Neo4jConfig | None = None) -> dict:
    """
    Returns a high-level summary of the entire repo graph:
    node counts by type, relationship counts by type, top-level folders/files.
    """
    cfg = config or load_neo4j_config()
    driver, session = _open_session(cfg)
    try:
        # Node counts by label i.e. type
        node_counts_result = session.run(
            """
            MATCH (r:Repository {name: $name})-[:CONTAINS*0..]->(n)
            UNWIND labels(n) AS lbl
            RETURN lbl, count(n) AS cnt
            """,
            name=repo_name,
        )
        node_counts = {r["lbl"]: r["cnt"] for r in node_counts_result}

        # Relationship counts by type
        rel_counts_result = session.run(
            """
            MATCH (r:Repository {name: $name})-[:CONTAINS*0..]->(a)
            MATCH (a)-[rel]->(b)
            RETURN type(rel) AS rel_type, count(rel) AS cnt
            """,
            name=repo_name,
        )
        rel_counts = {r["rel_type"]: r["cnt"] for r in rel_counts_result}

        # Top-level folders and root files
        top_level_result = session.run(
            """
            MATCH (r:Repository {name: $name})-[:CONTAINS]->(child)
            RETURN child.path AS path, labels(child)[0] AS type
            ORDER BY type, path
            """,
            name=repo_name,
        )
        top_level = [{"path": r["path"], "type": r["type"]} for r in top_level_result]

        # Repo node itself
        repo_result = session.run(
            "MATCH (r:Repository {name: $name}) RETURN r.id AS id, r.path AS path",
            name=repo_name,
        )
        repo_row = repo_result.single()

        return {
            "repo_name": repo_name,
            "repo_id": repo_row["id"] if repo_row else None,
            "repo_path": repo_row["path"] if repo_row else None,
            "node_counts": node_counts,
            "relationship_counts": rel_counts,
            "top_level_entries": top_level,
        }
    finally:
        session.close()
        driver.close()


# ---------------------------------------------------------------------------
# Query: everything inside a folder path
# ---------------------------------------------------------------------------
def read_folder_subgraph(
    repo_name: str,
    folder_path: str,
    config: Neo4jConfig | None = None,
) -> GraphSlice:
    """
    Loads all nodes reachable under a specific folder within the repo.
    folder_path is the repo-relative posix path, e.g. "src/utils".
    Returns nodes + all edges between those nodes.
    """
    cfg = config or load_neo4j_config()
    driver, session = _open_session(cfg)
    try:
        # Find folder node
        folder_result = session.run(
            """
            MATCH (r:Repository {name: $repo_name})-[:CONTAINS*1..]->(f:Folder {path: $folder_path})
            RETURN f.id AS folder_id
            """,
            repo_name=repo_name,
            folder_path=folder_path,
        )
        folder_row = folder_result.single()
        if folder_row is None:
            return GraphSlice(nodes=[], edges=[], warnings=[
                f"Folder '{folder_path}' not found in repo '{repo_name}'"
            ])
        folder_id = folder_row["folder_id"]

        # All nodes reachable from this folder via CONTAINS (any depth)
        nodes_result = session.run(
            """
            MATCH (f {id: $folder_id})-[:CONTAINS*0..]->(n)
            RETURN n
            """,
            folder_id=folder_id,
        )
        nodes = [_node_from_record(r) for r in nodes_result]
        node_ids = {n.id for n in nodes}

        # All edges where both endpoints are within this subgraph
        edges_result = session.run(
            """
            MATCH (f {id: $folder_id})-[:CONTAINS*0..]->(a)
            MATCH (a)-[r]->(b)
            WHERE b.id IN $node_ids
            RETURN a.id AS source_id, r, b.id AS target_id
            """,
            folder_id=folder_id,
            node_ids=list(node_ids),
        )
        edges = _run_and_collect_edges(session, "", **{})  # handled inline below
        edges = []
        for rec in session.run(
            """
            MATCH (f {id: $folder_id})-[:CONTAINS*0..]->(a)
            MATCH (a)-[r]->(b)
            WHERE b.id IN $node_ids
            RETURN a.id AS source_id, r, b.id AS target_id
            """,
            folder_id=folder_id,
            node_ids=list(node_ids),
        ):
            rel = rec["r"]
            edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))

        return GraphSlice(nodes=nodes, edges=edges, warnings=[])
    finally:
        session.close()
        driver.close()


# ---------------------------------------------------------------------------
# Query: single file view
# ---------------------------------------------------------------------------
def read_file_subgraph(
    repo_name: str,
    file_path: str,
    config: Neo4jConfig | None = None,
) -> GraphSlice:
    """
    Loads the full subgraph for one file: the file node, all symbols it defines
    (classes, functions, methods), and any cross-file CALLS or EXTENDS edges
    touching those symbols (with the remote endpoint included as a node).
    file_path is repo-relative, e.g. "src/utils/helpers.py".
    """
    cfg = config or load_neo4j_config()
    driver, session = _open_session(cfg)
    try:
        # File node
        file_result = session.run(
            """
            MATCH (r:Repository {name: $repo_name})-[:CONTAINS*1..]->(f:File {path: $file_path})
            RETURN f.id AS file_id
            """,
            repo_name=repo_name,
            file_path=file_path,
        )
        file_row = file_result.single()
        if file_row is None:
            return GraphSlice(nodes=[], edges=[], warnings=[
                f"File '{file_path}' not found in repo '{repo_name}'"
            ])
        file_id = file_row["file_id"]

        # All nodes defined inside this file (file itself + its symbols at any depth)
        internal_nodes_result = session.run(
            """
            MATCH (f {id: $file_id})-[:DEFINES|CONTAINS*0..]->(n)
            RETURN n
            """,
            file_id=file_id,
        )
        internal_nodes = [_node_from_record(r) for r in internal_nodes_result]
        internal_ids = {n.id for n in internal_nodes}

        # Internal edges
        internal_edges: list[EdgeRecord] = []
        for rec in session.run(
            """
            MATCH (a)-[r]->(b)
            WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.id AS source_id, r, b.id AS target_id
            """,
            ids=list(internal_ids),
        ):
            rel = rec["r"]
            internal_edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))

        # Cross-file CALLS edges OUT (symbols in this file call external targets)
        outbound_result = session.run(
            """
            MATCH (a)-[r:CALLS]->(b)
            WHERE a.id IN $ids AND NOT b.id IN $ids
            RETURN a.id AS source_id, r, b.id AS target_id, b AS target_node
            """,
            ids=list(internal_ids),
        )
        extra_nodes: list[NodeRecord] = []
        extra_edges: list[EdgeRecord] = []
        for rec in outbound_result:
            rel = rec["r"]
            b = rec["target_node"]
            labels = list(b.labels)
            extra_nodes.append(NodeRecord(
                id=b["id"],
                type=labels[0] if labels else "Unknown",
                properties=dict(b),
            ))
            extra_edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))

        # Cross-file CALLS edges IN (external symbols calling into this file)
        inbound_result = session.run(
            """
            MATCH (a)-[r:CALLS]->(b)
            WHERE b.id IN $ids AND NOT a.id IN $ids
            RETURN a.id AS source_id, r, b.id AS target_id, a AS source_node
            """,
            ids=list(internal_ids),
        )
        for rec in inbound_result:
            rel = rec["r"]
            a = rec["source_node"]
            labels = list(a.labels)
            extra_nodes.append(NodeRecord(
                id=a["id"],
                type=labels[0] if labels else "Unknown",
                properties=dict(a),
            ))
            extra_edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))

        # Cross-file EXTENDS edges
        extends_result = session.run(
            """
            MATCH (a)-[r:EXTENDS]->(b)
            WHERE (a.id IN $ids AND NOT b.id IN $ids)
               OR (b.id IN $ids AND NOT a.id IN $ids)
            RETURN a.id AS source_id, r, b.id AS target_id, a AS source_node, b AS target_node
            """,
            ids=list(internal_ids),
        )
        for rec in extends_result:
            rel = rec["r"]
            for side_key, id_key in [("source_node", "source_id"), ("target_node", "target_id")]:
                node = rec[side_key]
                node_id = rec[id_key]
                if node_id not in internal_ids:
                    labels = list(node.labels)
                    extra_nodes.append(NodeRecord(
                        id=node["id"],
                        type=labels[0] if labels else "Unknown",
                        properties=dict(node),
                    ))
            extra_edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))

        # Deduplicate extra nodes by id
        seen_ids = set(internal_ids)
        deduped_extra: list[NodeRecord] = []
        for n in extra_nodes:
            if n.id not in seen_ids:
                seen_ids.add(n.id)
                deduped_extra.append(n)

        return GraphSlice(
            nodes=internal_nodes + deduped_extra,
            edges=internal_edges + extra_edges,
            warnings=[],
        )
    finally:
        session.close()
        driver.close()


# ---------------------------------------------------------------------------
# Query: symbol lookup (class / function / method by name)
# ---------------------------------------------------------------------------
def read_symbol(
    repo_name: str,
    symbol_name: str,
    symbol_type: str | None = None,
    config: Neo4jConfig | None = None,
) -> GraphSlice:
    """
    Finds all nodes matching a symbol name (optionally filtered by type:
    Class, Function, Method) and returns them with their immediate
    relationships (1-hop in all directions).
    """
    cfg = config or load_neo4j_config()
    driver, session = _open_session(cfg)
    try:
        # Build type filter clause
        type_clause = f"AND n:{symbol_type}" if symbol_type else ""

        symbol_result = session.run(
            f"""
            MATCH (r:Repository {{name: $repo_name}})-[:CONTAINS*0..]->(n)
            WHERE n.name = $symbol_name {type_clause}
            RETURN n
            """,
            repo_name=repo_name,
            symbol_name=symbol_name,
        )
        root_nodes = [_node_from_record(r) for r in symbol_result]
        if not root_nodes:
            return GraphSlice(nodes=[], edges=[], warnings=[
                f"Symbol '{symbol_name}' not found in repo '{repo_name}'"
                + (f" (type filter: {symbol_type})" if symbol_type else "")
            ])

        root_ids = {n.id for n in root_nodes}
        all_nodes: list[NodeRecord] = list(root_nodes)
        all_edges: list[EdgeRecord] = []
        seen_ids = set(root_ids)

        # Outbound edges (1-hop)
        for rec in session.run(
            """
            MATCH (n)-[r]->(m)
            WHERE n.id IN $ids
            RETURN n.id AS source_id, r, m.id AS target_id, m AS neighbour
            """,
            ids=list(root_ids),
        ):
            rel = rec["r"]
            m = rec["neighbour"]
            m_id = rec["target_id"]
            all_edges.append(EdgeRecord(
                source_id=rec["source_id"],
                rel_type=rel.type,
                target_id=m_id,
                properties=dict(rel),
            ))
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                labels = list(m.labels)
                all_nodes.append(NodeRecord(
                    id=m["id"],
                    type=labels[0] if labels else "Unknown",
                    properties=dict(m),
                ))

        # Inbound edges (1-hop)
        for rec in session.run(
            """
            MATCH (m)-[r]->(n)
            WHERE n.id IN $ids
            RETURN m.id AS source_id, r, n.id AS target_id, m AS neighbour
            """,
            ids=list(root_ids),
        ):
            rel = rec["r"]
            m = rec["neighbour"]
            m_id = rec["source_id"]
            all_edges.append(EdgeRecord(
                source_id=m_id,
                rel_type=rel.type,
                target_id=rec["target_id"],
                properties=dict(rel),
            ))
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                labels = list(m.labels)
                all_nodes.append(NodeRecord(
                    id=m["id"],
                    type=labels[0] if labels else "Unknown",
                    properties=dict(m),
                ))

        return GraphSlice(nodes=all_nodes, edges=all_edges, warnings=[])
    finally:
        session.close()
        driver.close()


# ---------------------------------------------------------------------------
# Query: call chain (callers + callees, configurable depth)

# ---------------------------------------------------------------------------
def read_call_chain(
    repo_name: str,
    symbol_name: str,
    direction: str = "both",   # "callers", "callees", "both"
    depth: int = 3,
    config: Neo4jConfig | None = None,
) -> GraphSlice:
    """
    Returns the CALLS subgraph around a named function/method.
    direction: "callers"  → who calls this symbol (inbound)
               "callees"  → what this symbol calls (outbound)
               "both"     → both directions
    depth: max hops to traverse (capped at 10 for safety).
    """
    cfg = config or load_neo4j_config()
    depth = min(depth, 10)
    driver, session = _open_session(cfg)
    try:
        # Resolve starting nodes (function or method matching the name, within the repo)
        start_result = session.run(
            """
            MATCH (r:Repository {name: $repo_name})-[:CONTAINS*0..]->(n)
            WHERE n.name = $symbol_name AND (n:Function OR n:Method)
            RETURN n
            """,
            repo_name=repo_name,
            symbol_name=symbol_name,
        )
        start_nodes = [_node_from_record(r) for r in start_result]
        if not start_nodes:
            return GraphSlice(nodes=[], edges=[], warnings=[
                f"No Function/Method named '{symbol_name}' found in repo '{repo_name}'"
            ])

        start_ids = {n.id for n in start_nodes}
        all_nodes: list[NodeRecord] = list(start_nodes)
        all_edges: list[EdgeRecord] = []
        seen_ids = set(start_ids)

        # Callees: outbound CALLS traversal
        if direction in ("callees", "both"):
            for rec in session.run(
                f"""
                MATCH (start)-[:CALLS*1..{depth}]->(n)
                WHERE start.id IN $start_ids
                RETURN n
                """,
                start_ids=list(start_ids),
            ):
                n = rec["n"]
                if n["id"] not in seen_ids:
                    seen_ids.add(n["id"])
                    labels = list(n.labels)
                    all_nodes.append(NodeRecord(
                        id=n["id"],
                        type=labels[0] if labels else "Unknown",
                        properties=dict(n),
                    ))
            # Edges
            for rec in session.run(
                f"""
                MATCH (a)-[r:CALLS]->(b)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id AS source_id, r, b.id AS target_id
                """,
                ids=list(seen_ids),
            ):
                rel = rec["r"]
                all_edges.append(EdgeRecord(
                    source_id=rec["source_id"],
                    rel_type=rel.type,
                    target_id=rec["target_id"],
                    properties=dict(rel),
                ))

        # Callers: inbound CALLS traversal
        if direction in ("callers", "both"):
            caller_ids: set[str] = set()
            for rec in session.run(
                f"""
                MATCH (n)-[:CALLS*1..{depth}]->(target)
                WHERE target.id IN $start_ids
                RETURN n
                """,
                start_ids=list(start_ids),
            ):
                n = rec["n"]
                n_id = n["id"]
                caller_ids.add(n_id)
                if n_id not in seen_ids:
                    seen_ids.add(n_id)
                    labels = list(n.labels)
                    all_nodes.append(NodeRecord(
                        id=n_id,
                        type=labels[0] if labels else "Unknown",
                        properties=dict(n),
                    ))
            # Inbound edges among resolved caller+start nodes
            all_caller_and_start = caller_ids | start_ids
            for rec in session.run(
                f"""
                MATCH (a)-[r:CALLS]->(b)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id AS source_id, r, b.id AS target_id
                """,
                ids=list(all_caller_and_start),
            ):
                rel = rec["r"]
                edge = EdgeRecord(
                    source_id=rec["source_id"],
                    rel_type=rel.type,
                    target_id=rec["target_id"],
                    properties=dict(rel),
                )
                # Avoid duplicates if direction == "both"
                if edge not in all_edges:
                    all_edges.append(edge)

        return GraphSlice(nodes=all_nodes, edges=all_edges, warnings=[])
    finally:
        session.close()
        driver.close()

# ---------------------------------------------------------------------------
# Query: blast radius — what is affected by a set of changed files?
# ---------------------------------------------------------------------------
def read_blast_radius(
    repo_name: str,
    changed_file_paths: list[str],
    depth: int = 3,
    config: Neo4jConfig | None = None,
) -> dict:
    """
    Given repo-relative file paths that changed, return every symbol and file
    transitively affected via CALLS edges (up to `depth` hops).
    """
    cfg = config or load_neo4j_config()
    depth = min(max(depth, 1), 10)
    driver, session = _open_session(cfg)

    try:
        if not changed_file_paths:
            return _blast_empty(repo_name, changed_file_paths, "No changed files provided.")

        # Step 1: resolve file nodes that exist in the graph
        file_rows = list(session.run(
            """
            MATCH (r:Repository {name: $repo_name})-[:CONTAINS*1..]->(f:File)
            WHERE f.path IN $paths
            RETURN f.id AS file_id, f.path AS file_path
            """,
            repo_name=repo_name,
            paths=changed_file_paths,
        ))
        found_paths = {r["file_path"] for r in file_rows}
        missing_paths = [p for p in changed_file_paths if p not in found_paths]
        file_ids = [r["file_id"] for r in file_rows]

        warnings: list[str] = []
        if missing_paths:
            warnings.append(f"Files not in graph (run build first?): {missing_paths}")

        if not file_ids:
            return _blast_empty(repo_name, changed_file_paths, warnings[0] if warnings else "")

        # Step 2: symbols defined in the changed files
        changed_syms = [
            _sym_row(r) for r in session.run(
                """
                MATCH (f)-[:DEFINES|CONTAINS*0..]->(sym)
                WHERE f.id IN $file_ids
                  AND (sym:Function OR sym:Method OR sym:Class)
                RETURN sym.id AS id, sym.name AS name, sym.qualname AS qualname,
                       sym.file_path AS file_path, labels(sym)[0] AS type
                """,
                file_ids=file_ids,
            )
        ]
        changed_sym_ids = [s["id"] for s in changed_syms]

        if not changed_sym_ids:
            warnings.append("Changed files contain no tracked symbols.")
            return {
                "repo_name": repo_name,
                "changed_files": sorted(found_paths),
                "changed_symbols": [],
                "affected_symbols": [],
                "affected_files": [],
                "total_changed_symbols": 0,
                "total_affected_symbols": 0,
                "total_affected_files": 0,
                "warnings": warnings,
            }

        # Step 3: callers of changed symbols (transitive, up to depth hops)
        affected_syms = [
            _sym_row(r) for r in session.run(
                f"""
                MATCH (caller)-[:CALLS*1..{depth}]->(target)
                WHERE target.id IN $changed_sym_ids
                  AND NOT caller.id IN $changed_sym_ids
                WITH DISTINCT caller
                RETURN caller.id AS id, caller.name AS name,
                       caller.qualname AS qualname, caller.file_path AS file_path,
                       labels(caller)[0] AS type
                """,
                changed_sym_ids=changed_sym_ids,
            )
        ]

        affected_files = sorted({s["file_path"] for s in affected_syms if s["file_path"]})

        return {
            "repo_name": repo_name,
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
        session.close()
        driver.close()


def _sym_row(r: Any) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "qualname": r["qualname"],
        "file_path": r["file_path"],
        "type": r["type"],
    }


def _blast_empty(repo_name: str, changed_files: list[str], warning: str) -> dict:
    return {
        "repo_name": repo_name,
        "changed_files": changed_files,
        "changed_symbols": [],
        "affected_symbols": [],
        "affected_files": [],
        "total_changed_symbols": 0,
        "total_affected_symbols": 0,
        "total_affected_files": 0,
        "warnings": [warning] if warning else [],
    }

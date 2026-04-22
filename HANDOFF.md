# ontology-mcp — Session Handoff

## What this project is
MCP server that indexes code repos into a local SQLite graph and exposes analysis tools to AI agents (Claude, Cursor, etc.).

- **Branch**: `branch-treesitter`
- **Working dir**: `/Users/bhaveshmandwani/Code/Python/Accion/ontology-mcp`
- **DB location per repo**: `{repo}/.ontology-mcp/graph.db`

---

## What was just completed (this session)

### Phase 1 — All done ✅
| Tool | Status |
|------|--------|
| A1 · `get_hub_nodes` | done |
| A2 · `find_large_functions` | done |
| A3 · `traverse_graph` | done |
| A4 · `detect_changes` (risk-scored) | done |
| A5 · incremental build (SHA-256 hashing) | done |
| Query tools consolidated (5 → 3) | done |

### B1 · `list_communities` — just implemented, needs smoke test ⚠️
**What was done:**
1. Added `communities` table + index to `_bootstrap()` in `sqlite_store.py`
2. Added `build_communities()` and `read_communities()` to `sqlite_store.py`
3. Created `src/ontology_mcp/tools/communities.py`
4. Registered `list_communities` tool in `server.py`

**Smoke test was interrupted** — still needs to be verified:
```bash
cd /Users/bhaveshmandwani/Code/Python/Accion/ontology-mcp
PYTHONPATH=src .venv/bin/python -c "
from ontology_mcp.tools.communities import get_list_communities
import json
# point at any repo that has a built graph
result = get_list_communities('<REPO_PATH>', top_n=5)
print(json.dumps(result, indent=2))
"
```

---

## File map (what lives where)

```
src/ontology_mcp/
├── server.py                        # MCP tool registrations
├── sqlite_store.py                  # ALL SQL read/write functions
├── tools/
│   ├── build_python_code_ontology.py  # scan → parse → write graph
│   ├── query_graph.py               # query(), query_graph_overview(), query_call_chain()
│   ├── blast_radius.py              # get_blast_radius()
│   ├── context_tools.py             # get_minimal_context(), get_review_context()
│   ├── hub_nodes.py                 # get_hub_nodes()
│   ├── large_functions.py           # get_large_functions()
│   ├── traverse.py                  # get_traverse()
│   ├── detect_changes.py            # get_detect_changes()
│   └── communities.py              # get_list_communities()  ← NEW (needs test)
├── parser.py                        # Python AST parser
├── ts_parser.py                     # tree-sitter multi-language parser
├── scanner.py                       # file discovery
├── model.py                         # Node, Edge, OntologyGraph
├── git_utils.py                     # get_git_modified_files()
└── config.py                        # excluded dirs, supported extensions
```

---

## Phase 2 — remaining work

| ID | Tool | Status | Depends on |
|----|------|--------|------------|
| B1 | `list_communities` | needs smoke test | — |
| B2 | `get_bridge_nodes` | not started | B1 |
| B3 | `get_knowledge_gaps` | not started | B1 |
| B4 | `get_architecture_overview` | not started | B1 |
| B5 | `list_flows` | not started | independent |

### B2 · `get_bridge_nodes`
Find nodes with high betweenness centrality — the chokepoints that connect communities.
- Use `nx.betweenness_centrality(G)` on the same graph built in B1
- Store results in a `bridge_nodes` table or compute on-the-fly

### B3 · `get_knowledge_gaps`
Find isolated nodes (no connections) and untested hotspots.
- Nodes with 0 edges = isolated
- Hub nodes (high degree) with no `test_*` callers = untested hotspots

### B4 · `get_architecture_overview`
Combined map: communities + bridge nodes + hub nodes in one call.

### B5 · `list_flows`
Entry point detection + BFS call path tracing.
- Entry points = nodes with 0 inbound CALLS edges (route handlers, main functions)
- Trace outward to show the full execution path

---

## How the build flow works (reminder)
```
build_python_code_ontology(repo_path)
  → scanner.scan_files()           — finds all files
  → parser.parse_python_files()    — Python AST
  → ts_parser.parse_file()         — JS/TS/Go/Rust/.NET
  → sqlite_store.write_graph()     — writes to SQLite
  → sqlite_store.write_file_hashes() — saves hashes for incremental builds
```

## Risk score formula (detect_changes)
```
risk = min(1.0, min(dependents/5, 0.7) + (0.3 if no_test else 0.0))
```

## Running the server
```bash
cd /Users/bhaveshmandwani/Code/Python/Accion/ontology-mcp
uv run ontology-mcp-server
```

# ontology-mcp — Session Handoff

## What this project is
MCP server that indexes code repos into a local SQLite graph and exposes analysis tools to AI agents (Claude, Cursor, etc.).

- **Branch**: `branch-treesitter`
- **Working dir**: `/Users/bhaveshmandwani/Code/Python/Accion/ontology-mcp`
- **DB location per repo**: `{repo}/.ontology-mcp/graph.db`

---

## What was completed

### Phase 1 — All done ✅
| Tool | Status |
|------|--------|
| A1 · `get_hub_nodes` | done |
| A2 · `find_large_functions` | done |
| A3 · `traverse_graph` | done |
| A4 · `detect_changes` (risk-scored) | done |
| A5 · incremental build (SHA-256 hashing) | done |
| Query tools consolidated (5 → 3) | done |

### Phase 2 — All done ✅
| Tool | Status |
|------|--------|
| B1 · `list_communities` | done |
| B2 · `get_bridge_nodes` | done |
| B3 · `get_knowledge_gaps` | done |
| B4 · `get_architecture_overview` | done |
| B5 · `list_flows` | done |

### Phase 3 — Not started
| ID | Tool | Agent problem it solves |
|----|------|------------------------|
| C1 | `resolve_symbol` | Sees same name in N files — returns only the relevant match using import chain from current file context. Replaces N file reads. |
| C2 | `find_circular_dependencies` | `nx.find_cycle()` on IMPORTS graph. Returns exact cycle chains. Agent cannot do this through reasoning alone. |
| C3 | `get_add_location` | "I need to add a function that calls A and B" — returns the right file based on community membership. Saves full codebase scan. |
| C4 | `find_similar_implementations` | Given callees needed, finds existing functions with same structural call pattern. Agent copies real code instead of hallucinating. |
| C5 | `get_vulnerability_surface` | Scans all flows for entry points with no auth function in call chain. Would take O(n) manual tool calls otherwise. |
| C6 | `get_context_window_pack` | Given a list of symbols the agent is working with, returns all their relationships in one batched call. Replaces N separate `query` calls. |

### Parser fix — nested functions ✅
Inner/nested functions (e.g. `role_checker` inside `require_roles`) now get a
`DEFINES` edge from their parent function. Previously they had 0 edges and
appeared as isolated dead code across all tools.

---

## File map (what lives where)

```
src/ontology_mcp/
├── server.py                          # MCP tool registrations
├── sqlite_store.py                    # ALL SQL read/write functions
├── tools/
│   ├── build_python_code_ontology.py  # scan → parse → write graph
│   ├── query_graph.py                 # query(), query_graph_overview(), query_call_chain()
│   ├── blast_radius.py                # get_blast_radius()
│   ├── context_tools.py               # get_minimal_context(), get_review_context()
│   ├── hub_nodes.py                   # get_hub_nodes()
│   ├── large_functions.py             # get_large_functions()
│   ├── traverse.py                    # get_traverse()
│   ├── detect_changes.py              # get_detect_changes()
│   ├── communities.py                 # get_list_communities()
│   ├── bridge_nodes.py                # get_bridge_nodes()
│   ├── knowledge_gaps.py              # get_knowledge_gaps()
│   ├── architecture_overview.py       # get_architecture_overview()
│   └── flows.py                       # get_list_flows()
├── parser.py                          # Python AST parser
├── ts_parser.py                       # tree-sitter multi-language parser
├── scanner.py                         # file discovery
├── model.py                           # Node, Edge, OntologyGraph
├── git_utils.py                       # get_git_modified_files()
└── config.py                          # excluded dirs, supported extensions
```

---

## SQLite tables
| Table | Purpose |
|-------|---------|
| `nodes` | All graph nodes (Repository, Folder, File, Class, Function, Method, Import) |
| `edges` | All relationships (CONTAINS, DEFINES, CALLS, IMPORTS, EXTENDS) |
| `file_hashes` | SHA-256 per file for incremental builds |
| `communities` | Louvain community assignments (node_id → community_id) |
| `bridge_nodes` | Betweenness centrality scores |
| `knowledge_gaps` | Isolated nodes + untested hotspots |
| `flows` | BFS call paths from entry points |

---

## Known limitation — sparse CALLS edges
The parser detects CALLS edges only for:
- Same-file calls (always)
- Cross-file calls where the callee is explicitly imported in the caller's file

FastAPI `Depends()` injection and SQLAlchemy patterns are NOT resolved as CALLS
edges. This makes communities cluster by file structure rather than call graph,
and flows only trace explicit call chains.

---

## How the build flow works
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

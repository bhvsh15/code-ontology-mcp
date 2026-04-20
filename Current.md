## MCP Tools (13 live tools)

### Agent Orientation
| Tool | What it does |
|------|-------------|
| `healthcheck` | Confirm the server is alive |
| `get_connection_info` | Return launch command, server path, credential status |
| `get_minimal_context` | ~100-token graph summary — first call any agent should make |
| `get_review_context` | Bundled review context: changed files + blast radius + summary in one call |

### Build & Index
| Tool | What it does |
|------|-------------|
| `build_python_code_ontology` | Scan + parse + write graph to SQLite |

### Git & Change Detection
| Tool | What it does |
|------|-------------|
| `get_changed_files` | List all uncommitted / staged / untracked files via git |
| `get_blast_radius` | Given changed files → find every symbol and file that depends on them via CALLS traversal |

### Graph Queries
| Tool | What it does |
|------|-------------|
| `query_graph_overview` | Node/edge counts + top-level folder structure |
| `query_folder` | Full subgraph for a folder (all nodes + edges within) |
| `query_file` | File's symbols + cross-file CALLS and EXTENDS edges |
| `query_symbol` | Named class/function/method + 1-hop neighbourhood |
| `query_call_chain` | Callers / callees traversal up to N hops (configurable direction + depth) |

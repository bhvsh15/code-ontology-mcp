# ontology-mcp — What We've Built

---

## Overview

**ontology-mcp** is an MCP (Model Context Protocol) server that indexes
any source-code repository into a local SQLite graph database and exposes
that graph as tools any AI agent can call — Claude, Antigravity, Cursor,
Codex, or any MCP-compatible client.

No external database, no cloud dependency, no credentials required.
The entire graph lives in `{repo}/.ontology-mcp/graph.db` alongside
the code it describes.

---

## Core Architecture

| Layer | What we built |
|-------|--------------|
| **Parsing** | Python AST parser + tree-sitter for 6 languages |
| **Storage** | Local SQLite — zero infra, ships with every repo |
| **Server** | FastMCP server over stdio / SSE |
| **Client config** | Auto-generated `mcp-config.json` for any MCP client |
| **Env management** | `.env` loader — no hardcoded credentials anywhere |

---

## Language Support

| Language | Extensions | Parser |
|----------|-----------|--------|
| Python | `.py` | Built-in AST (deep, accurate) |
| JavaScript | `.js` `.jsx` `.mjs` | tree-sitter |
| TypeScript | `.ts` `.tsx` | tree-sitter |
| C# | `.cs` | tree-sitter |
| Go | `.go` | tree-sitter |
| Rust | `.rs` | tree-sitter |

Extracts: classes, functions, methods, imports, call sites, inheritance.

---

## Graph Schema

### Node Types
| Type | Description |
|------|-------------|
| `Repository` | Root node — one per indexed repo |
| `Folder` | Directory in the file tree |
| `File` | Source file with language tag |
| `Class` | Class / struct / interface definition |
| `Function` | Module-level or free function |
| `Method` | Function inside a class |
| `Import` | Module or symbol import |

### Edge Types
| Relationship | Description |
|-------------|-------------|
| `CONTAINS` | Structural hierarchy (repo → folder → file → symbol) |
| `DEFINES` | File defines a class or function |
| `IMPORTS` | File imports a module or symbol |
| `EXTENDS` | Class inherits from another class |
| `CALLS` | Function calls another function (cross-file resolved) |

---

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

---

## Key Engineering Decisions

### Local SQLite — No External Database
Every repo carries its own `.ontology-mcp/graph.db`.
- Zero infra cost for clients
- Works offline and on-prem
- Trivially shareable (one file)
- Git-ignored by default

### Edge Deduplication on Write
The parser can emit the same structural edge multiple times (one per file
in the same folder). We deduplicate at write time using a Python set,
keeping the database clean without requiring unique constraints.

### Cross-File CALLS Resolution
Python imports are resolved by walking up the directory tree from the
importing file, matching `from auth.utils import foo` to
`backend/auth/utils.py` even when the repo root isn't the Python path.
This is the primary reason CALLS edges exist in the graph at all.

### Dual Parser Architecture
Python files use the built-in `ast` module (precise, no extra deps).
Non-Python files use `tree-sitter-language-pack` (one package, 6
languages). Both parsers write into the same `OntologyGraph` model so
queries don't need to know which parser produced a given node.

---

## Agent Integration

Tested and working with:

| Agent | Config file |
|-------|------------|
| **Antigravity** | `~/.gemini/antigravity/mcp_config.json` |
| **Claude Desktop / Code** | Standard `mcpServers` JSON block |
| **Cursor** | `.cursor/mcp.json` |
| Any MCP client | `mcp-config.json` at project root |

Credentials (if used for Neo4j during dev) are loaded from a `.env` file
in the project root — never hardcoded, never committed.

---

## Interactive Visualisation

A D3.js force-directed graph rendered as a self-contained HTML file:

- Colour-coded nodes by type (Repository, Folder, File, Class, Function…)
- Directional arrows per edge type
- Hover tooltips with qualified name, file path, line number
- Legend toggles to show/hide node types
- Search bar to highlight nodes by name
- Zoom + pan + drag

```bash
PYTHONPATH=src python -m ontology_mcp.visualize /path/to/your/repo
```

---

## Test Coverage

| Test | What it validates |
|------|-------------------|
| `test_dry_run_builds_graph` | Full parse pipeline on a synthetic mini-repo; asserts node + edge counts |
| `test_scanner_finds_backend_python_files` | Scanner correctly filters by glob and excludes standard dirs |
| `test_ontology_tool_dry_run_returns_counts` | End-to-end dry run on a real project |

---

## What's Coming Next

| Capability | Status |
|-----------|:------:|
| Community detection | 🔜 |
| Hub & bridge node analysis | 🔜 |
| Execution flow tracing | 🔜 |
| Risk-scored change detection | 🔜 |
| Incremental builds (file hashing) | 🔜 |
| Semantic search | 🔜 |
| Vulnerability surface detection | 🔜 |
| PR checklist generator | 🔜 |

> ✅ Done · 🔜 Roadmap

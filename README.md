# ontology-mcp

**A graph-based MCP server that gives AI coding agents precise structural knowledge of any codebase — without reading entire files.**

Instead of burning tokens loading irrelevant code, agents call targeted tools that answer questions like: *"What breaks if I change this?"*, *"Where should I add this function?"*, *"Which endpoints have no auth?"* — in one call, using a pre-built graph.

---

## How it works

`ontology-mcp` scans your repository, parses every file using Python's AST and Tree-sitter, and builds a structural graph stored in a local SQLite database at `{repo}/.ontology-mcp/graph.db`.

```
Repository
  → Scanner        finds all files
  → Parser         extracts classes, functions, imports, call sites
  → Graph          nodes + edges written to SQLite
  → MCP tools      agents query the graph instead of reading files
```

**Nodes tracked**: Repository, Folder, File, Class, Function, Method, Import

**Edges tracked**: `CONTAINS`, `DEFINES`, `CALLS`, `IMPORTS`, `EXTENDS`

---

## Quick start

```bash
# Install
pip install ontology-mcp   # or: pipx install ontology-mcp

# Add to your MCP client config
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server"
    }
  }
}

# Build the graph for your repo
build_python_code_ontology(repo_path="/path/to/your/repo")
```

Requires Python 3.9+. No external database — everything is local SQLite.

---

## Languages supported

| Language | Parser |
|----------|--------|
| Python | AST (built-in) + Tree-sitter |
| JavaScript / TypeScript | Tree-sitter |
| Go | Tree-sitter |
| Rust | Tree-sitter |
| C# / .NET | Tree-sitter |

---

## All tools

### Build

| Tool | What it does |
|------|-------------|
| `build_python_code_ontology` | Scan and index a repo into local SQLite. Supports incremental builds — only re-parses changed files using SHA-256 hashing. |

### Query

| Tool | What it does |
|------|-------------|
| `query_graph_overview` | Node and edge counts, top-level structure. Call this first. |
| `query` | Look up a file, folder, or symbol with its 1-hop neighbours. |
| `query_call_chain` | Callers and callees of any function, traversable to N hops. |
| `traverse_graph` | Walk the graph from any node following any edge type. |

### Context (token-saving bundles)

| Tool | What it does |
|------|-------------|
| `get_minimal_context` | ~100-token repo summary. The first call an agent should make. |
| `get_review_context` | Changed files + blast radius in one call — saves 3-4 round trips. |

### Impact analysis

| Tool | What it does |
|------|-------------|
| `detect_changes` | Git-aware risk-scored report: what changed, what it affects, risk 0–1. |
| `get_blast_radius` | Everything that depends on a set of files, traced via CALLS edges. |

### Architecture

| Tool | What it does |
|------|-------------|
| `get_architecture_overview` | One-call codebase map: communities + bridge nodes + hub nodes. |
| `list_communities` | Groups related code into logical clusters using the Louvain algorithm. |
| `get_bridge_nodes` | Chokepoints that connect different communities — touching these breaks the most. |
| `get_hub_nodes` | Most connected symbols by degree, filterable by type. |
| `get_knowledge_gaps` | Isolated nodes (dead code) and high-traffic symbols with no tests. |
| `list_flows` | Entry points (route handlers, main functions) with their full BFS call paths. |
| `find_large_functions` | Functions exceeding a line count threshold. |

### Agent-accuracy tools

| Tool | What it does |
|------|-------------|
| `resolve_symbol` | Disambiguates a symbol name using the import chain from the current file. When `get_db` exists in 8 files, returns only the one in scope. |
| `find_circular_dependencies` | Detects circular import chains across the codebase. Returns exact file paths forming each cycle. |
| `get_add_location` | Given symbols a new function will interact with, suggests the right file to add it to based on community membership. |
| `find_similar_implementations` | Given callees a new function needs, finds existing functions with the same call pattern — ranked by overlap. |
| `get_vulnerability_surface` | Flags entry points with no auth function in their call chain. |
| `get_context_window_pack` | Batch lookup for multiple symbols — returns all their nodes, edges, and neighbours in one call instead of N separate queries. |

---

## Why the agent-accuracy tools matter

Standard code tools tell agents *what exists*. These tools tell agents *what to do* — without wasting tokens on guesswork.

**`resolve_symbol`** — Agents frequently edit the wrong file when a function name is defined in multiple places. This resolves the correct one using import chain analysis.

**`get_add_location`** — Without this, agents scan the entire codebase to decide where to put new code. This returns the answer in one call.

**`find_similar_implementations`** — Agents hallucinate code patterns. This finds real existing patterns to copy from.

**`get_context_window_pack`** — Replaces N `query()` calls with one batched subgraph lookup. For a 5-symbol task, saves 4 round trips.

**`get_vulnerability_surface`** — Security review that would take O(n) manual tool calls returns in one.

**`find_circular_dependencies`** — Graph cycle detection is impossible to do through reasoning alone at scale.

---

## Risk score formula

```
risk = min(1.0, min(dependents/5, 0.7) + (0.3 if no_test_callers else 0.0))
```

Used by `detect_changes` to rank which changed symbols need the most attention.

---

## Graph database location

Each repo gets its own isolated database:

```
{repo_path}/.ontology-mcp/graph.db
```

No credentials, no cloud dependency.

---

## MCP client configuration

**Claude Code / Claude Desktop**
```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server"
    }
  }
}
```

**Cursor**

Add to Cursor MCP settings or `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server"
    }
  }
}
```

**uv (recommended)**
```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "uvx",
      "args": ["ontology-mcp-server"]
    }
  }
}
```

---

## Development

```bash
git clone https://github.com/bhvsh15/code-ontology-mcp.git
cd code-ontology-mcp
uv venv && source .venv/bin/activate
uv pip install -e .
uv run ontology-mcp-server
```

---

## Licence

MIT

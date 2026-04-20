# Enhancements Roadmap

Feature backlog for ontology-mcp. This file is for **forward-looking features** —
bug fixes and refactors live in [improvements.md](improvements.md).

## Status legend

- [ ] planned — not started
- [~] in progress
- [x] done
- [?] needs design / open question

Update the checkbox when status changes, and link the PR or commit in the
**Notes** column so the history is traceable.

---

## 1. Ingestion & Language Support

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1.1 | Incremental updates (re-parse only changed files, <2s on repeat runs) | [ ] | Depends on file-hash cache + git change detection (1.2) |
| 1.2 | Git change detection | [x] | Implemented in [git_utils.py](src/ontology_mcp/git_utils.py) + `get_changed_files` tool |
| 1.3 | Multi-language parsers (TS/TSX, JS, Vue, Svelte, Go, Rust, Java, Scala, C#, Ruby, Kotlin, Swift, PHP, Solidity, C/C++, Dart, R, Perl, Lua, Zig, PowerShell, Julia) | [ ] | Today only Python AST is supported in [parser.py](src/ontology_mcp/parser.py). Likely needs tree-sitter. |
| 1.4 | Jupyter / Databricks `.ipynb` ingestion | [ ] | Extract code cells, treat as virtual `.py` |
| 1.5 | Watch mode (continuous graph updates as you work) | [ ] | File-system watcher on top of incremental updates |
| 1.6 | Auto-update hooks (file edit + git commit) | [ ] | Git `post-commit` + editor hook that calls `build_python_code_ontology` |

## 2. Graph Analysis

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 2.1 | Blast-radius analysis (functions/classes/files affected by a change) | [x] | `read_blast_radius` in neo4j_reader.py + `get_blast_radius` tool |
| 2.3 | Community detection via Leiden | [ ] | Needs APOC / GDS in Neo4j, or in-memory on small graphs |
| 2.4 | Community auto-split when one community >25% of graph | [ ] | Post-step of 2.3 |
| 2.5 | Surprise scoring (cross-community / cross-language / peripheral→hub edges) | [ ] | Depends on 2.2 + 2.3 |
| 2.6 | Knowledge gap analysis (isolated nodes, untested hotspots, thin communities) | [ ] | |
| 2.7 | Execution flows (trace call chains from entry points, weighted by criticality) | [ ] | Extends [query_call_chain](src/ontology_mcp/tools/query_graph.py) |
| 2.8 | Architecture overview with coupling warnings | [ ] | Aggregates 2.2 + 2.3 |
| 2.9 | Edge confidence scoring (EXTRACTED / INFERRED / AMBIGUOUS, float) | [ ] | Add `confidence` to `Edge.properties` in [model.py](src/ontology_mcp/model.py) |

## 3. Search & Queries

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 3.1 | Semantic search via sentence-transformers / Gemini / MiniMax | [?] | Pluggable embedder interface; store vectors on nodes |
| 3.2 | Full-text search (FTS5 hybrid keyword + vector) | [?] | FTS5 implies SQLite — conflicts with Neo4j-only (see 6.1) |
| 3.3 | Graph traversal tool (free-form BFS/DFS, depth + token budget) | [ ] | Generalizes `query_call_chain` |
| 3.4 | Suggested questions auto-generated from graph (bridges, hubs, surprises) | [ ] | Depends on 2.2, 2.5 |

## 4. Review, Refactor & Risk

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 4.1 | `detect_changes` — diff → affected functions / flows / test gaps | [ ] | Builds on 1.2 + 2.1 |
| 4.2 | Rename preview (symbol-aware) | [ ] | |
| 4.3 | Framework-aware dead-code detection | [ ] | Needs framework entry-point registry |
| 4.4 | Community-driven refactor suggestions | [ ] | Depends on 2.3 |
| 4.5 | MCP prompt templates: review, architecture, debug, onboard, pre-merge | [ ] | Register with FastMCP `@mcp.prompt` |

## 5. Output, Export & Visualisation

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 5.1 | Interactive D3 force-directed visualisation (search, legend, degree-scaled nodes) | [ ] | Static HTML export, no server required |
| 5.2 | Export: GraphML (Gephi/yEd) | [ ] | |
| 5.3 | Export: Neo4j Cypher script | [ ] | |
| 5.4 | Export: Obsidian vault (wikilinks) | [ ] | |
| 5.5 | Export: static SVG graph | [ ] | |
| 5.6 | Wiki generation from community structure | [ ] | Markdown output, depends on 2.3 |
| 5.7 | Graph diff between snapshots (new/removed nodes, edges, community churn) | [ ] | Requires snapshot storage |
| 5.8 | Token benchmarking (naive full-corpus tokens vs graph query tokens, per-question ratios) | [ ] | |
| 5.9 | Memory loop — persist Q&A as markdown, re-ingest into graph | [ ] | |

## 6. Storage & Infrastructure

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 6.1 | Local-only SQLite backend (`.code-review-graph/`), no external DB required | [ ] | **Decided: replace Neo4j with SQLite.** Reason: client privacy + no infra dependency = sellable. Migrate after blast-radius (2.1) is stable. |
| 6.2 | Multi-repo registry (register many repos, cross-repo search) | [ ] | Today `repo_name` is scoped per-call; needs an index node |
| 6.3 | Codex / Cursor agent bridge (env detection, `.env`, `mcp-config.json`, `get_connection_info` tool) | [x] | `setup_env.py` + `get_connection_info` tool + `mcp-config.json` |

---

## Working order (suggested)

1. Finish **6.3** — agent bridge, so other tools can drive the MCP reliably.
2. **1.1 + 1.2** — incremental updates built on top of already-landed git detection.
3. **2.1 + 4.1** — blast radius and `detect_changes`, the most visible reviewer value.
4. **2.2, 2.3, 2.5** — centrality + communities unlock many downstream features (2.8, 3.4, 4.4, 5.6).
5. Exports and visualisation (**5.x**) once the analysis layer is stable.
6. Language expansion (**1.3, 1.4**) — largest scope, defer until the Python path is polished.

## Open design questions

- **Storage:** ~~SQLite vs. Neo4j-only~~ → **decided: SQLite** (6.1). Client privacy + zero infra = product. Neo4j stays for internal dev until 6.1 lands. Affects 3.1, 3.2, 5.7.
- **Embeddings provider:** pluggable interface, or pick one default? (3.1)
- **Parser layer:** tree-sitter vs. per-language AST libraries for 1.3.
- **Incremental identity:** current SHA1 IDs are content-based — verify they stay stable enough for cheap diffs in 1.1 / 5.7.

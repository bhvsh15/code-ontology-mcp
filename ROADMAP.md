# ontology-mcp — Roadmap

A code intelligence layer for AI agents — parse any Python repo into a graph, query it for architecture insights, change impact, and review support.

---

## Phase 1 — Core Agent Tools
- **Hub nodes** — most-connected symbols (highest refactor risk)
- **Large function detection** — flag oversized functions/classes
- **Graph traversal** — BFS/DFS across any edge types
- **Risk-scored change detection** — blast radius + test gaps + security flags
- **Incremental builds** — skip unchanged files via file hash cache

## Phase 2 — Architecture Analysis
- **Community detection** — group related code into logical clusters
- **Bridge nodes** — chokepoints between communities
- **Knowledge gaps** — dead code, orphaned files, untested hotspots
- **Architecture overview** — one-call codebase map
- **Execution flows** — trace entry points to full call paths

## Phase 3 — Differentiators
- **PR checklist generator** — auto-generate a structured pre-merge review checklist from blast radius + test gaps + risk scores
- **Precise test coverage** — for every function, show exactly which tests cover it (semantic, not line-based)
- **Explain call chain** — natural language walkthrough of any call path between two symbols

---


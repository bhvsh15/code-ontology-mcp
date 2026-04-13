# ontology-mcp (Python MCP Server)

Learning-first MCP server for building Python code ontologies in Neo4j.

## What this teaches
- MCP server creation in Python (FastMCP)
- Tool design for agent usage
- Cross-agent MCP integration via stdio command wiring
- LLM-independent code graph extraction

## Exposed MCP tools
- `healthcheck`
- `build_python_code_ontology`

## Tool parameters (`build_python_code_ontology`)
- `repo_path` (required)
- `include_globs` (optional, default `["**/*.py"]`)
- `exclude_globs` (optional, merged with default excludes)
- `reset_graph` (default `true`)
- `dry_run` (default `false`)

## Environment variables (for write mode)
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional, default `neo4j`)

## Run locally (development)
```bash
PYTHONPATH=src python -m ontology_mcp
```

## Package install options (recommended for agent integration)
```bash
# pipx (global isolated tool)
pipx install .

# uv tool install (if you use uv)
uv tool install .
```

After install, command is:
```bash
ontology-mcp-server
```

## Generic MCP config (stdio)
Use this shape in clients that support custom MCP servers:

```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server",
      "args": [],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "NEO4J_DATABASE": "neo4j"
      }
    }
  }
}
```

## Cursor MCP config example
Place in Cursor MCP settings JSON (or project `.mcp.json`, based on your setup):

```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server",
      "args": [],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password"
      }
    }
  }
}
```

## Claude Desktop MCP config example
Typical macOS location:
`~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ontology-mcp": {
      "command": "ontology-mcp-server",
      "args": [],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password"
      }
    }
  }
}
```

## Learning progression (recommended)
1. Run with `dry_run=true` first.
2. Inspect node/relationship counts.
3. Configure Neo4j env vars.
4. Run with `dry_run=false`.
5. Visualize graph in Neo4j Browser.

## Notes
- Current extraction is Python-focused and rule-based.
- `CALLS` is best-effort for cross-file resolution.
- Start with high precision and grow coverage iteratively.

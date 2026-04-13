# Improvements

## Overview

This project has a nice, simple architecture:

1. MCP server entrypoint
2. Repository scanning
3. AST parsing into an ontology graph
4. Optional Neo4j persistence

That flow is easy to understand, but there are a few issues worth fixing before the project is reliable to run or share.

## Suggested Improvements

### 1. Fix the `Node` and `Edge` field-name mismatch

The graph model and its callers are currently out of sync.

- In `src/ontology_mcp/model.py`, `Node` defines `properties` and `Edge` defines `properties`.
- In `src/ontology_mcp/parser.py`, nodes and edges are created using `props=...`.
- In `src/ontology_mcp/neo4j_writer.py`, the writer reads `node.props` and `edge.props`.

This causes the main dry-run path to fail with:

```text
TypeError: Node.__init__() got an unexpected keyword argument 'props'
```

Recommended fix:

- Standardize on one attribute name everywhere, preferably `properties`.
- Update parser and writer to use the same field names as the dataclasses.
- Add a test that exercises a full dry-run path so this kind of regression is caught immediately.

### 2. Replace hardcoded Neo4j credentials with environment-variable loading

`src/ontology_mcp/neo4j_writer.py` currently hardcodes the Neo4j URI, username, password, and database.

Why this should change:

- It conflicts with the README, which documents env-var configuration.
- It is unsafe to keep credentials in source code.
- It makes local development and deployment less flexible.

Recommended fix:

- Read `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, and optional `NEO4J_DATABASE` from the environment.
- Raise a clear error if required values are missing.
- Keep any protocol normalization logic only if it is truly needed.

### 3. Make the tests self-contained and portable

The current tests depend on local machine state:

- `tests/test_smoke.py` references an absolute path to another repo on disk.
- `tests/test_neo4j.py` acts like a live connectivity script and requires the `neo4j` package plus working external credentials.

Why this matters:

- The tests will fail on any other machine or CI environment.
- They do not provide deterministic validation of the project itself.

Recommended fix:

- Replace the absolute-path sample repo with a temporary test fixture created inside the test.
- Convert the Neo4j test into a mocked unit test, or mark live integration tests separately.
- Ensure the default `pytest` run works offline and without external services.

### 4. Make the test runner work from a clean checkout

`pytest` currently fails during collection in a clean environment because:

- `ontology_mcp` is not importable unless `PYTHONPATH=src` is set.
- `neo4j` may not be installed in the active environment.

Recommended fix:

- Configure the project so tests run cleanly after installing dependencies.
- Consider adding a pytest configuration or a standard development setup command.
- Keep the default test suite limited to unit tests that do not require optional external services.

### 5. Add one end-to-end dry-run test

The main user-facing value of the project is the ontology build flow. A small end-to-end dry-run test would protect that path.

Recommended coverage:

- Create a temporary mini Python repo inside the test.
- Run `build_python_code_ontology(..., dry_run=True)`.
- Assert file counts, node counts, relationship counts, and `neo4j_status == "skipped (dry_run)"`.

This would catch model/parser/writer contract drift very early.

## Priority Order

Suggested order of work:

1. Fix the `props` vs `properties` mismatch.
2. Remove hardcoded Neo4j credentials and load from env vars.
3. Replace brittle tests with self-contained tests.
4. Add a true dry-run end-to-end test.
5. Improve developer setup so `pytest` works predictably.

## Expected Outcome

After these changes, the project should be:

- runnable in `dry_run` mode without crashing
- safer to share and commit
- easier to test locally and in CI
- more reliable as an MCP server example project

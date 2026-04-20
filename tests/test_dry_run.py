from __future__ import annotations

from pathlib import Path

import pytest

from ontology_mcp.neo4j_writer import Neo4jConfigError, load_neo4j_config
from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path / "pkg" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "pkg" / "core.py",
        "class Greeter:\n"
        "    def hello(self) -> str:\n"
        "        return 'hi'\n"
        "\n"
        "def shout(g: Greeter) -> str:\n"
        "    return g.hello().upper()\n",
    )
    _write(
        tmp_path / "app.py",
        "from pkg.core import shout, Greeter\n"
        "\n"
        "def main() -> None:\n"
        "    print(shout(Greeter()))\n",
    )
    return tmp_path


def test_dry_run_builds_graph_without_neo4j(mini_repo: Path) -> None:
    result = build_python_code_ontology(repo_path=str(mini_repo), dry_run=True)

    assert result["status"] == "dry_run_completed"
    assert result["neo4j_status"] == "skipped (dry_run)"
    assert result["nodes_written"] == 0
    assert result["files_scanned"] >= 2

    node_counts = result["node_counts"]
    assert node_counts.get("Repository", 0) == 1
    assert node_counts.get("File", 0) >= 2
    assert node_counts.get("Class", 0) >= 1
    assert node_counts.get("Function", 0) >= 1
    assert node_counts.get("Method", 0) >= 1

    rel_counts = result["relationship_counts"]
    assert rel_counts.get("CONTAINS", 0) >= 1
    assert rel_counts.get("DEFINES", 0) >= 1


def test_load_neo4j_config_raises_when_required_vars_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("NEO4J_URI", "NEO4J_PASSWORD", "NEO4J_USERNAME", "NEO4J_DATABASE"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(Neo4jConfigError) as exc:
        load_neo4j_config()

    message = str(exc.value)
    assert "NEO4J_URI" in message
    assert "NEO4J_PASSWORD" in message


def test_load_neo4j_config_returns_values_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    cfg = load_neo4j_config()
    assert cfg.uri == "bolt://localhost:7687"
    assert cfg.username == "neo4j"
    assert cfg.password == "secret"
    assert cfg.database == "neo4j"

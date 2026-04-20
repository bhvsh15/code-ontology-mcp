from __future__ import annotations

from pathlib import Path

from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_dry_run_builds_graph(tmp_path: Path) -> None:
    _write(tmp_path / "pkg" / "__init__.py", "")
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

    result = build_python_code_ontology(repo_path=str(tmp_path), dry_run=True)

    assert result["status"] == "dry_run_completed"
    assert result["store_status"] == "skipped (dry_run)"
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

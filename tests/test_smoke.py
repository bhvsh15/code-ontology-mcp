from __future__ import annotations

from ontology_mcp.scanner import scan_python_files
from ontology_mcp.tools.build_python_code_ontology import build_python_code_ontology


SAMPLE_REPO = "/Users/bhaveshmandwani/Code/Python/INTERNSHIP/Crud_FastAPI"


def test_scanner_finds_backend_python_files() -> None:
    result = scan_python_files(SAMPLE_REPO, include_globs=["backend/**/*.py"])
    assert len(result.files) > 0
    assert all("/backend/" in f for f in result.files)


def test_ontology_tool_dry_run_returns_counts() -> None:
    result = build_python_code_ontology(
        repo_path=SAMPLE_REPO,
        include_globs=["backend/**/*.py"],
        dry_run=True,
    )
    assert result["status"] == "dry_run_completed"
    assert result["files_scanned"] > 0
    assert result["neo4j_status"] == "skipped (dry_run)"
    assert result["nodes_written"] == 0

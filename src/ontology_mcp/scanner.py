from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from ontology_mcp.config import DEFAULT_EXCLUDES

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "env",
}

#Structured output of the scanning process, including the repo path, list of included files, and list of excluded directories
@dataclass(frozen=True)
class ScanResult:
    repo_path: str
    files: list[str]
    excluded_dirs: list[str]

#Helper function to check if a given file path should be excluded based on the exclude patterns, relative to the repo root
def _is_excluded(path: Path, repo_root: Path, exclude_globs: list[str]) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    return any(fnmatch(rel, pattern) for pattern in exclude_globs)

#Scan the given repository path for Python files 
def scan_python_files(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> ScanResult:
    root = Path(repo_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"repo_path does not exist: {repo_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"repo_path is not a directory: {repo_path}")

    include = include_globs or ["**/*.py"]
    exclude = (exclude_globs or []) + DEFAULT_EXCLUDES

    files: list[str] = []
    for path in root.rglob("*.py"):
        rel_parts = path.relative_to(root).parts
        if any(part in DEFAULT_EXCLUDE_DIRS for part in rel_parts):
            continue
        if _is_excluded(path, root, exclude):
            continue
        rel = path.relative_to(root).as_posix()
        if include and not any(fnmatch(rel, p) for p in include):
            continue
        files.append(str(path))

    files.sort()
    return ScanResult(
        repo_path=str(root),
        files=files,
        excluded_dirs=sorted(DEFAULT_EXCLUDE_DIRS),
    )

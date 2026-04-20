"""
File discovery for ontology-mcp.

Walks a repository directory and returns paths to all source files that
the parser layer supports.  Applies exclusion patterns from ``config.py``
plus any caller-supplied globs, then optionally filters to a specific set
of languages.

Supported languages and their extensions
-----------------------------------------
python      .py
javascript  .js  .jsx  .mjs
typescript  .ts  .tsx
csharp      .cs
go          .go
rust        .rs
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from ontology_mcp.config import DEFAULT_EXCLUDES

DEFAULT_EXCLUDE_DIRS = {
    ".git", "venv", ".venv", "__pycache__", "node_modules",
    "dist", "build", "env", ".ontology-mcp",
}

LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "python":     [".py"],
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts", ".tsx"],
    "csharp":     [".cs"],
    "go":         [".go"],
    "rust":       [".rs"],
}

ALL_EXTENSIONS: frozenset[str] = frozenset(
    ext for exts in LANGUAGE_EXTENSIONS.values() for ext in exts
)


def language_for(path: Path) -> str | None:
    """Return the language name for a file path, or ``None`` if unsupported."""
    suffix = path.suffix.lower()
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if suffix in exts:
            return lang
    return None


@dataclass(frozen=True)
class ScanResult:
    """Output of a scan: resolved paths, excluded directories, and per-language counts."""

    repo_path: str
    files: list[str]
    excluded_dirs: list[str]
    languages_found: dict[str, int]


def _is_excluded(path: Path, repo_root: Path, exclude_globs: list[str]) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    return any(fnmatch(rel, pattern) for pattern in exclude_globs)


def scan_files(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    languages: list[str] | None = None,
) -> ScanResult:
    """
    Recursively scan ``repo_path`` and return all supported source files.

    Parameters
    ----------
    repo_path:
        Absolute path to the repository root.
    include_globs:
        Whitelist of fnmatch patterns (repo-relative).  Defaults to all
        files whose extension matches the requested languages.
    exclude_globs:
        Additional patterns to exclude on top of ``DEFAULT_EXCLUDES``.
    languages:
        Restrict to specific language keys (e.g. ``["python", "go"]``).
        Defaults to all supported languages.
    """
    root = Path(repo_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"repo_path does not exist: {repo_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"repo_path is not a directory: {repo_path}")

    allowed_exts: frozenset[str] = (
        frozenset(
            ext
            for lang in languages
            for ext in LANGUAGE_EXTENSIONS.get(lang, [])
        )
        if languages else ALL_EXTENSIONS
    )

    exclude = (exclude_globs or []) + DEFAULT_EXCLUDES
    include = include_globs or [f"**/*{ext}" for ext in allowed_exts]

    files: list[str] = []
    lang_counts: dict[str, int] = {}

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in allowed_exts:
            continue
        # Fast directory-level exclusion before the costlier glob check
        if any(part in DEFAULT_EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        if _is_excluded(path, root, exclude):
            continue
        rel = path.relative_to(root).as_posix()
        if not any(fnmatch(rel, p) for p in include):
            continue
        files.append(str(path))
        lang = language_for(path) or "unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    files.sort()
    return ScanResult(
        repo_path=str(root),
        files=files,
        excluded_dirs=sorted(DEFAULT_EXCLUDE_DIRS),
        languages_found=lang_counts,
    )


def scan_python_files(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> ScanResult:
    """Backward-compatible alias that restricts scanning to Python files only."""
    return scan_files(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        languages=["python"],
    )

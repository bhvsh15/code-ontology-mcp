"""
Shared configuration constants for the ontology-mcp scanner.

``DEFAULT_EXCLUDES`` is a list of glob patterns applied to every scan.
Any repo-relative path that matches one of these patterns is silently
skipped before parsing, regardless of what ``include_globs`` the caller
passes.  The patterns follow Python's ``fnmatch`` syntax (the same as
``pathlib.Path.match``).

Adding a pattern here affects all tools — build, incremental update,
blast-radius, etc. — so only put entries here that should *always* be
excluded (dependency caches, build artefacts, VCS metadata).
"""

from __future__ import annotations

DEFAULT_EXCLUDES = [
    ".git/**",
    "venv/**",
    ".venv/**",
    "__pycache__/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "env/**",
    ".ontology-mcp/**",   # our own graph database directory
]

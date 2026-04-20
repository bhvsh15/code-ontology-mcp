"""
Git utilities for detecting changed files in a local repository.

Used by blast-radius analysis and the ``get_changed_files`` MCP tool to
determine which files have been touched since the last commit, so the
graph can answer "what is affected by my current changes?" without a
full rebuild.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_modified_files(repo_path: str) -> list[str]:
    """
    Return a sorted, deduplicated list of repo-relative file paths that are
    currently modified, staged, or untracked (honouring ``.gitignore``).

    Combines three git queries:
    - ``git diff --name-only HEAD``      — unstaged + staged tracked changes
    - ``git diff --name-only --cached``  — staged-only (handles fresh repos
                                           with no commits yet)
    - ``git ls-files --others --exclude-standard`` — untracked files

    Returns an empty list — without raising — when ``repo_path`` is not
    inside a git repository or git is not installed.
    """
    root = Path(repo_path).resolve()
    if not root.is_dir():
        return []

    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    files: set[str] = set()

    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if result.returncode == 0:
            files.update(line for line in result.stdout.splitlines() if line)

    return sorted(files)

from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_modified_files(repo_path: str) -> list[str]:
    """
    Return a deduplicated list of repo-relative paths for files that have
    uncommitted changes, are staged, or are untracked (excluding .gitignore'd
    files).

    Returns an empty list if *repo_path* is not inside a git repository.
    """
    root = Path(repo_path).resolve()
    if not root.is_dir():
        return []

    try:
        # Verify this is a git repo
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    files: set[str] = set()

    # Staged + unstaged tracked changes (modified, deleted, added)
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        files.update(line for line in result.stdout.splitlines() if line)

    # Also catch staged-only changes (e.g. in a fresh repo with no commits)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        files.update(line for line in result.stdout.splitlines() if line)

    # Untracked files (respects .gitignore)
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        files.update(line for line in result.stdout.splitlines() if line)

    return sorted(files)

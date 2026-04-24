from __future__ import annotations

import re
import subprocess
from pathlib import Path


_REPOS_DIR = Path.home() / ".ontology-mcp" / "repos"


def _repo_slug(github_url: str) -> str:
    """Extract 'user-repo' from any GitHub URL variant."""
    clean = github_url.rstrip("/").removesuffix(".git")
    match = re.search(r"github\.com[/:](.+)/(.+)$", clean)
    if not match:
        raise ValueError(f"Could not parse GitHub URL: {github_url}")
    return f"{match.group(1)}-{match.group(2)}"


def _to_https(github_url: str) -> str:
    """Normalise SSH URLs to HTTPS."""
    if github_url.startswith("git@github.com:"):
        path = github_url.removeprefix("git@github.com:").removesuffix(".git")
        return f"https://github.com/{path}.git"
    if not github_url.endswith(".git"):
        return github_url + ".git"
    return github_url


def clone_or_pull(github_url: str) -> tuple[str, str]:
    """
    Clone the repo if it doesn't exist locally, otherwise git pull.
    Returns (local_path, action) where action is 'cloned' or 'updated'.
    """
    slug = _repo_slug(github_url)
    local_path = _REPOS_DIR / slug
    _REPOS_DIR.mkdir(parents=True, exist_ok=True)

    if local_path.exists():
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=local_path,
            check=True,
            capture_output=True,
        )
        return str(local_path), "updated"
    else:
        subprocess.run(
            ["git", "clone", "--depth=1", _to_https(github_url), str(local_path)],
            check=True,
            capture_output=True,
        )
        return str(local_path), "cloned"

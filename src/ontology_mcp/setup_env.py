from __future__ import annotations

import os
import sys
from pathlib import Path

_REQUIRED = ("NEO4J_URI", "NEO4J_PASSWORD")
_OPTIONAL = {"NEO4J_USERNAME": "neo4j", "NEO4J_DATABASE": "neo4j"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Load vars from a .env file into os.environ without overwriting existing values."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _missing() -> list[str]:
    return [v for v in _REQUIRED if not os.environ.get(v, "").strip()]


def ensure_env() -> dict:
    """
    Ensure Neo4j env vars are present.

    Resolution order:
      1. Existing os.environ values.
      2. Project-root .env file.
      3. Interactive prompt when stdin is a tty.

    Returns a status dict — does not raise; callers decide how to handle missing vars.
    """
    dotenv_path = _project_root() / ".env"
    _load_dotenv(dotenv_path)

    # Fill optional vars with defaults when absent
    for var, default in _OPTIONAL.items():
        os.environ.setdefault(var, default)

    missing = _missing()

    if missing and sys.stdin.isatty():
        print(
            "[ontology-mcp] Some Neo4j env vars are missing. Enter values (blank to skip):",
            file=sys.stderr,
        )
        for var in missing:
            try:
                value = input(f"  {var}: ").strip()
            except EOFError:
                break
            if value:
                os.environ[var] = value
        missing = _missing()

    if missing:
        print(
            "[ontology-mcp] WARNING: "
            + ", ".join(missing)
            + f" not set. Add them to {dotenv_path} or export them in your shell.",
            file=sys.stderr,
        )

    return {
        "dotenv_path": str(dotenv_path),
        "dotenv_exists": dotenv_path.is_file(),
        "missing": missing,
        "ready": not missing,
    }


if __name__ == "__main__":
    status = ensure_env()
    if status["ready"]:
        print("[ontology-mcp] Neo4j env vars present — ready to connect.")
    else:
        sys.exit(1)
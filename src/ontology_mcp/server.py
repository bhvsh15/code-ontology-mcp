from __future__ import annotations

from fastmcp import FastMCP

from ontology_mcp.tools.build_python_code_ontology import (
    build_python_code_ontology as build_python_code_ontology_impl,
)

mcp = FastMCP(name="ontology-mcp")


@mcp.tool
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "ontology-mcp"}


@mcp.tool
def build_python_code_ontology(
    repo_path: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    reset_graph: bool = True,
    dry_run: bool = False,
) -> dict:
    return build_python_code_ontology_impl(
        repo_path=repo_path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        reset_graph=reset_graph,
        dry_run=dry_run,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

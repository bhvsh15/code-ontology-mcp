from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from ontology_mcp.model import Edge, Node, OntologyGraph


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.append(("name", node.func.id))
        elif isinstance(node.func, ast.Attribute):
            self.calls.append(("attr", node.func.attr))
        self.generic_visit(node)


def parse_python_files(repo_path: str, files: list[str]) -> OntologyGraph:
    repo_root = Path(repo_path).resolve()
    graph = OntologyGraph()
    repo_id = _stable_id("repo", str(repo_root))
    graph.add_node(
        Node(
            id=repo_id,
            type="Repository",
            props={"id": repo_id, "name": repo_root.name, "path": str(repo_root)},
        )
    )

    symbol_index_by_name: dict[str, list[str]] = {}
    file_ids: dict[str, str] = {}
    function_calls_by_source: list[tuple[str, list[tuple[str, str]]]] = []

    for fpath in files:
        rel = Path(fpath).resolve().relative_to(repo_root).as_posix()
        file_id = _stable_id("file", str(repo_root), rel)
        file_ids[fpath] = file_id
        graph.add_node(
            Node(
                id=file_id,
                type="File",
                props={
                    "id": file_id,
                    "path": rel,
                    "name": Path(rel).name,
                    "extension": ".py",
                },
            )
        )
        graph.add_edge(Edge(source_id=repo_id, rel_type="CONTAINS", target_id=file_id))

        parent = Path(rel).parent
        if str(parent) != ".":
            parts = parent.parts
            current = ""
            parent_ids: list[str] = []
            for part in parts:
                current = f"{current}/{part}" if current else part
                folder_id = _stable_id("folder", str(repo_root), current)
                parent_ids.append(folder_id)
                graph.add_node(
                    Node(
                        id=folder_id,
                        type="Folder",
                        props={"id": folder_id, "path": current, "name": part},
                    )
                )
            graph.add_edge(
                Edge(source_id=repo_id, rel_type="CONTAINS", target_id=parent_ids[0])
            )
            for i in range(1, len(parent_ids)):
                graph.add_edge(
                    Edge(
                        source_id=parent_ids[i - 1],
                        rel_type="CONTAINS",
                        target_id=parent_ids[i],
                    )
                )
            graph.add_edge(
                Edge(source_id=parent_ids[-1], rel_type="CONTAINS", target_id=file_id)
            )

        text = _read_text(fpath)
        try:
            tree = ast.parse(text, filename=fpath)
        except SyntaxError as exc:
            graph.warnings.append(f"SyntaxError in {rel}: {exc}")
            continue

        imports_seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp_id = _stable_id("import", str(repo_root), rel, str(node.lineno), alias.name)
                    if imp_id in imports_seen:
                        continue
                    imports_seen.add(imp_id)
                    graph.add_node(
                        Node(
                            id=imp_id,
                            type="Import",
                            props={
                                "id": imp_id,
                                "module": alias.name,
                                "symbol": None,
                                "alias": alias.asname,
                                "file_path": rel,
                                "lineno": node.lineno,
                            },
                        )
                    )
                    graph.add_edge(Edge(file_id, "DEFINES", imp_id))
                    graph.add_edge(Edge(file_id, "IMPORTS", imp_id))
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    imp_id = _stable_id(
                        "import",
                        str(repo_root),
                        rel,
                        str(node.lineno),
                        base,
                        alias.name,
                    )
                    if imp_id in imports_seen:
                        continue
                    imports_seen.add(imp_id)
                    graph.add_node(
                        Node(
                            id=imp_id,
                            type="Import",
                            props={
                                "id": imp_id,
                                "module": base,
                                "symbol": alias.name,
                                "alias": alias.asname,
                                "file_path": rel,
                                "lineno": node.lineno,
                            },
                        )
                    )
                    graph.add_edge(Edge(file_id, "DEFINES", imp_id))
                    graph.add_edge(Edge(file_id, "IMPORTS", imp_id))

        for top in tree.body:
            if isinstance(top, ast.ClassDef):
                class_qualname = f"{rel}:{top.name}"
                class_id = _stable_id("class", str(repo_root), class_qualname, str(top.lineno))
                graph.add_node(
                    Node(
                        id=class_id,
                        type="Class",
                        props={
                            "id": class_id,
                            "name": top.name,
                            "qualname": class_qualname,
                            "file_path": rel,
                            "lineno": top.lineno,
                        },
                    )
                )
                graph.add_edge(Edge(file_id, "DEFINES", class_id))
                symbol_index_by_name.setdefault(top.name, []).append(class_id)

                for base in top.bases:
                    base_name = None
                    if isinstance(base, ast.Name):
                        base_name = base.id
                    elif isinstance(base, ast.Attribute):
                        base_name = base.attr
                    if base_name:
                        target_stub_id = _stable_id("class_ref", str(repo_root), base_name)
                        graph.add_node(
                            Node(
                                id=target_stub_id,
                                type="Class",
                                props={
                                    "id": target_stub_id,
                                    "name": base_name,
                                    "qualname": base_name,
                                    "file_path": None,
                                    "lineno": None,
                                    "external_ref": True,
                                },
                            )
                        )
                        graph.add_edge(Edge(class_id, "EXTENDS", target_stub_id))

                for item in top.body:
                    if isinstance(item, ast.FunctionDef):
                        method_qualname = f"{rel}:{top.name}.{item.name}"
                        method_id = _stable_id(
                            "method",
                            str(repo_root),
                            method_qualname,
                            str(item.lineno),
                        )
                        graph.add_node(
                            Node(
                                id=method_id,
                                type="Method",
                                props={
                                    "id": method_id,
                                    "name": item.name,
                                    "qualname": method_qualname,
                                    "file_path": rel,
                                    "lineno": item.lineno,
                                },
                            )
                        )
                        graph.add_edge(Edge(class_id, "HAS_METHOD", method_id))
                        graph.add_edge(Edge(file_id, "DEFINES", method_id))
                        symbol_index_by_name.setdefault(item.name, []).append(method_id)

                        collector = _CallCollector()
                        collector.visit(item)
                        function_calls_by_source.append((method_id, collector.calls))

            elif isinstance(top, ast.FunctionDef):
                fn_qualname = f"{rel}:{top.name}"
                fn_id = _stable_id("function", str(repo_root), fn_qualname, str(top.lineno))
                graph.add_node(
                    Node(
                        id=fn_id,
                        type="Function",
                        props={
                            "id": fn_id,
                            "name": top.name,
                            "qualname": fn_qualname,
                            "file_path": rel,
                            "lineno": top.lineno,
                        },
                    )
                )
                graph.add_edge(Edge(file_id, "DEFINES", fn_id))
                symbol_index_by_name.setdefault(top.name, []).append(fn_id)

                collector = _CallCollector()
                collector.visit(top)
                function_calls_by_source.append((fn_id, collector.calls))

    for source_id, calls in function_calls_by_source:
        for call_kind, call_name in calls:
            candidates = symbol_index_by_name.get(call_name, [])
            if not candidates:
                continue
            if len(candidates) == 1:
                graph.add_edge(
                    Edge(
                        source_id=source_id,
                        rel_type="CALLS",
                        target_id=candidates[0],
                        props={"confidence": "high", "kind": call_kind},
                    )
                )
            else:
                for candidate in candidates:
                    graph.add_edge(
                        Edge(
                            source_id=source_id,
                            rel_type="CALLS",
                            target_id=candidate,
                            props={"confidence": "medium", "kind": call_kind},
                        )
                    )

    return graph

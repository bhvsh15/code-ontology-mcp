from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from ontology_mcp.model import Edge, Node, OntologyGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _base_name(node: ast.expr) -> str | None:
    """Extract a simple name from a base-class expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    # e.g.  Generic[T]  ->  Generic
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


# ---------------------------------------------------------------------------
# Call collector  (both sync and async bodies)
# ---------------------------------------------------------------------------

class _CallCollector(ast.NodeVisitor):
    """
    Collect every call site inside a function/method body.
    Records (kind, name) tuples where kind is "name" or "attr".
    Does NOT descend into nested class definitions to avoid
    attributing inner-class calls to the outer method.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.append(("name", node.func.id))
        elif isinstance(node.func, ast.Attribute):
            self.calls.append(("attr", node.func.attr))
        self.generic_visit(node)

    # Don't descend into nested class bodies from here
    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# Recursive class / function walker
# ---------------------------------------------------------------------------

# Both sync and async function node types
_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _collect_class_and_func_nodes(
    body: list[ast.stmt],
) -> tuple[list[ast.ClassDef], list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    """
    Recursively pull ClassDef and FunctionDef/AsyncFunctionDef nodes out of
    *any* statement list (including if-blocks, try-blocks, with-blocks, etc.)
    so that we don't miss definitions buried in guards like
    `if __name__ == "__main__":`.
    """
    classes: list[ast.ClassDef] = []
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    for stmt in body:
        if isinstance(stmt, ast.ClassDef):
            classes.append(stmt)
        elif isinstance(stmt, _FUNC_TYPES):
            funcs.append(stmt)
        else:
            # Recurse into compound statements
            for child_list in _child_bodies(stmt):
                sub_cls, sub_fns = _collect_class_and_func_nodes(child_list)
                classes.extend(sub_cls)
                funcs.extend(sub_fns)

    return classes, funcs


def _child_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Return all nested statement lists of a compound statement."""
    results: list[list[ast.stmt]] = []
    # if / elif / else
    if isinstance(stmt, ast.If):
        results.append(stmt.body)
        results.append(stmt.orelse)
    # for / while
    elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        results.append(stmt.body)
        results.append(stmt.orelse)
    # try
    elif isinstance(stmt, ast.Try):
        results.append(stmt.body)
        results.append(stmt.orelse)
        results.append(stmt.finalbody)
        for handler in stmt.handlers:
            results.append(handler.body)
    # with
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        results.append(stmt.body)
    # match (Python 3.10+)
    elif hasattr(ast, "Match") and isinstance(stmt, ast.Match):
        for case in stmt.cases:
            results.append(case.body)
    return results


def _collect_methods(
    class_body: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """
    Collect all method definitions from a class body, including those hidden
    behind decorators, `if TYPE_CHECKING` guards, etc.
    Excludes nested class definitions (they are handled separately).
    """
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for stmt in class_body:
        if isinstance(stmt, _FUNC_TYPES):
            methods.append(stmt)
        elif not isinstance(stmt, ast.ClassDef):
            for child_list in _child_bodies(stmt):
                for s in child_list:
                    if isinstance(s, _FUNC_TYPES):
                        methods.append(s)
    return methods


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_python_files(repo_path: str, files: list[str]) -> OntologyGraph:
    repo_root = Path(repo_path).resolve()
    graph = OntologyGraph()
    repo_id = _stable_id("repo", str(repo_root))
    graph.add_node(
        Node(
            id=repo_id,
            type="Repository",
            properties={"id": repo_id, "name": repo_root.name, "path": str(repo_root)},
        )
    )

    # name -> list[node_id]  (used for CALLS resolution)
    symbol_index: dict[str, list[str]] = {}
    # (source_id, [(kind, name)])
    pending_calls: list[tuple[str, list[tuple[str, str]]]] = []
    # class name -> list[class_id]  (for EXTENDS resolution)
    class_index: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Pass 1 – build folder hierarchy + file nodes + AST symbols
    # ------------------------------------------------------------------
    for fpath in files:
        fpath_obj = Path(fpath).resolve()
        rel = fpath_obj.relative_to(repo_root).as_posix()
        file_id = _stable_id("file", str(repo_root), rel)

        graph.add_node(
            Node(
                id=file_id,
                type="File",
                properties={
                    "id": file_id,
                    "path": rel,
                    "name": fpath_obj.name,
                    "extension": ".py",
                },
            )
        )

        # --- folder hierarchy ------------------------------------------------
        parent = Path(rel).parent
        if str(parent) != ".":
            parts = parent.parts
            current = ""
            folder_ids: list[str] = []
            for part in parts:
                current = f"{current}/{part}" if current else part
                folder_id = _stable_id("folder", str(repo_root), current)
                folder_ids.append(folder_id)
                graph.add_node(
                    Node(
                        id=folder_id,
                        type="Folder",
                        properties={"id": folder_id, "path": current, "name": part},
                    )
                )

            # repo → first folder (only if not already added by a sibling file)
            graph.add_edge(Edge(source_id=repo_id, rel_type="CONTAINS", target_id=folder_ids[0]))
            # folder → sub-folder chain
            for i in range(1, len(folder_ids)):
                graph.add_edge(
                    Edge(
                        source_id=folder_ids[i - 1],
                        rel_type="CONTAINS",
                        target_id=folder_ids[i],
                    )
                )
            # last folder → file  (NOT repo → file, to avoid double edge)
            graph.add_edge(
                Edge(source_id=folder_ids[-1], rel_type="CONTAINS", target_id=file_id)
            )
        else:
            # File sits at repo root
            graph.add_edge(Edge(source_id=repo_id, rel_type="CONTAINS", target_id=file_id))

        # --- parse AST -------------------------------------------------------
        text = _read_text(fpath)
        try:
            tree = ast.parse(text, filename=fpath)
        except SyntaxError as exc:
            graph.warnings.append(f"SyntaxError in {rel}: {exc}")
            continue

        # Imports are intentionally skipped — Import nodes clutter the graph
        # and are toggled OFF in the UI. Re-enable here if needed in future.

        # Classes and functions (recursive, catches nested defs)
        all_classes, top_funcs = _collect_class_and_func_nodes(tree.body)

        # --- top-level classes -----------------------------------------------
        for cls_node in all_classes:
            _process_class(
                cls_node=cls_node,
                parent_id=file_id,
                file_id=file_id,
                rel=rel,
                repo_root=repo_root,
                graph=graph,
                symbol_index=symbol_index,
                class_index=class_index,
                pending_calls=pending_calls,
            )

        # --- top-level functions (including async) ---------------------------
        for fn_node in top_funcs:
            _process_function(
                fn_node=fn_node,
                parent_id=file_id,
                file_id=file_id,
                rel=rel,
                repo_root=repo_root,
                graph=graph,
                symbol_index=symbol_index,
                pending_calls=pending_calls,
                node_type="Function",
            )

    # ------------------------------------------------------------------
    # Pass 2 – resolve EXTENDS now that all classes are indexed
    # ------------------------------------------------------------------
    # We deferred EXTENDS edges so we can point to real node IDs
    for edge in list(graph.edges):
        if edge.rel_type == "EXTENDS":
            # target is currently a stub id; replace with real id if resolvable
            # (stubs are written with type="Class" and external_ref=True)
            pass  # stubs remain; resolution happens below via class_index

    # Re-wire EXTENDS edges that used stub IDs
    # The stubs were added with id=_stable_id("class_ref", repo_root, base_name)
    # Now we check if the real class exists in class_index and patch the edge.
    # Since Edge is frozen we rebuild the edge list.
    new_edges: list[Edge] = []
    for edge in graph.edges:
        if edge.rel_type == "EXTENDS":
            stub_node = graph.nodes.get(edge.target_id)
            if stub_node and stub_node.properties.get("external_ref"):
                base_name_val = stub_node.properties.get("name", "")
                real_ids = class_index.get(base_name_val, [])
                if len(real_ids) == 1:
                    new_edges.append(
                        Edge(
                            source_id=edge.source_id,
                            rel_type="EXTENDS",
                            target_id=real_ids[0],
                            properties={"resolved": True},
                        )
                    )
                    continue
                elif len(real_ids) > 1:
                    for rid in real_ids:
                        new_edges.append(
                            Edge(
                                source_id=edge.source_id,
                                rel_type="EXTENDS",
                                target_id=rid,
                                properties={"resolved": True, "confidence": "medium"},
                            )
                        )
                    continue
        new_edges.append(edge)
    graph.edges = new_edges

    # ------------------------------------------------------------------
    # Pass 3 – resolve CALLS
    # ------------------------------------------------------------------
    for source_id, calls in pending_calls:
        for call_kind, call_name in calls:
            candidates = symbol_index.get(call_name, [])
            if not candidates:
                continue
            if len(candidates) == 1:
                graph.add_edge(
                    Edge(
                        source_id=source_id,
                        rel_type="CALLS",
                        target_id=candidates[0],
                        properties={"confidence": "high", "kind": call_kind},
                    )
                )
            else:
                for candidate in candidates:
                    graph.add_edge(
                        Edge(
                            source_id=source_id,
                            rel_type="CALLS",
                            target_id=candidate,
                            properties={"confidence": "medium", "kind": call_kind},
                        )
                    )

    return graph


# ---------------------------------------------------------------------------
# Helpers for processing classes and functions
# ---------------------------------------------------------------------------

def _process_class(
    cls_node: ast.ClassDef,
    parent_id: str,
    file_id: str,
    rel: str,
    repo_root: Path,
    graph: OntologyGraph,
    symbol_index: dict[str, list[str]],
    class_index: dict[str, list[str]],
    pending_calls: list[tuple[str, list[tuple[str, str]]]],
    outer_qualname: str = "",
) -> str:
    """Register a class node and all its methods/nested classes. Returns class_id."""
    qualname = f"{outer_qualname}.{cls_node.name}" if outer_qualname else f"{rel}:{cls_node.name}"
    class_id = _stable_id("class", str(repo_root), qualname, str(cls_node.lineno))

    graph.add_node(
        Node(
            id=class_id,
            type="Class",
            properties={
                "id": class_id,
                "name": cls_node.name,
                "qualname": qualname,
                "file_path": rel,
                "lineno": cls_node.lineno,
                "is_async": False,
            },
        )
    )
    graph.add_edge(Edge(parent_id, "DEFINES", class_id))
    symbol_index.setdefault(cls_node.name, []).append(class_id)
    class_index.setdefault(cls_node.name, []).append(class_id)

    # Base classes → EXTENDS (use stub; will be resolved in pass 2)
    for base in cls_node.bases:
        base_name = _base_name(base)
        if base_name and base_name not in ("object",):
            stub_id = _stable_id("class_ref", str(repo_root), base_name)
            # Only add stub if not already a real class node
            if stub_id not in graph.nodes:
                graph.add_node(
                    Node(
                        id=stub_id,
                        type="Class",
                        properties={
                            "id": stub_id,
                            "name": base_name,
                            "qualname": base_name,
                            "file_path": None,
                            "lineno": None,
                            "external_ref": True,
                        },
                    )
                )
            graph.add_edge(Edge(class_id, "EXTENDS", stub_id))

    # Methods (sync + async)
    for method_node in _collect_methods(cls_node.body):
        _process_function(
            fn_node=method_node,
            parent_id=class_id,
            file_id=file_id,
            rel=rel,
            repo_root=repo_root,
            graph=graph,
            symbol_index=symbol_index,
            pending_calls=pending_calls,
            node_type="Method",
            outer_qualname=qualname,
            use_has_method=True,
        )

    # Nested classes
    for stmt in cls_node.body:
        if isinstance(stmt, ast.ClassDef):
            _process_class(
                cls_node=stmt,
                parent_id=class_id,
                file_id=file_id,
                rel=rel,
                repo_root=repo_root,
                graph=graph,
                symbol_index=symbol_index,
                class_index=class_index,
                pending_calls=pending_calls,
                outer_qualname=qualname,
            )

    return class_id


def _process_function(
    fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_id: str,
    file_id: str,
    rel: str,
    repo_root: Path,
    graph: OntologyGraph,
    symbol_index: dict[str, list[str]],
    pending_calls: list[tuple[str, list[tuple[str, str]]]],
    node_type: str = "Function",
    outer_qualname: str = "",
    use_has_method: bool = False,
) -> str:
    """Register a function/method node. Returns its ID."""
    is_async = isinstance(fn_node, ast.AsyncFunctionDef)
    sep = "." if node_type == "Method" else ":"
    qualname = (
        f"{outer_qualname}{sep}{fn_node.name}"
        if outer_qualname
        else f"{rel}:{fn_node.name}"
    )
    prefix = "method" if node_type == "Method" else "function"
    fn_id = _stable_id(prefix, str(repo_root), qualname, str(fn_node.lineno))

    # Decorators as a list of names for metadata
    decorator_names: list[str] = []
    for dec in fn_node.decorator_list:
        if isinstance(dec, ast.Name):
            decorator_names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            decorator_names.append(dec.attr)
        elif isinstance(dec, ast.Call):
            inner = dec.func
            if isinstance(inner, ast.Name):
                decorator_names.append(inner.id)
            elif isinstance(inner, ast.Attribute):
                decorator_names.append(inner.attr)

    graph.add_node(
        Node(
            id=fn_id,
            type=node_type,  # type: ignore[arg-type]
            properties={
                "id": fn_id,
                "name": fn_node.name,
                "qualname": qualname,
                "file_path": rel,
                "lineno": fn_node.lineno,
                "is_async": is_async,
                "decorators": ", ".join(decorator_names) if decorator_names else None,
            },
        )
    )

    if use_has_method:
        graph.add_edge(Edge(parent_id, "HAS_METHOD", fn_id))
    else:
        graph.add_edge(Edge(parent_id, "DEFINES", fn_id))

    graph.add_edge(Edge(file_id, "DEFINES", fn_id))
    symbol_index.setdefault(fn_node.name, []).append(fn_id)

    # Collect call sites within this function body
    collector = _CallCollector()
    collector.visit(fn_node)
    pending_calls.append((fn_id, collector.calls))

    # Handle nested functions (closures / inner functions)
    inner_cls, inner_fns = _collect_class_and_func_nodes(fn_node.body)
    for inner_fn in inner_fns:
        _process_function(
            fn_node=inner_fn,
            parent_id=fn_id,
            file_id=file_id,
            rel=rel,
            repo_root=repo_root,
            graph=graph,
            symbol_index=symbol_index,
            pending_calls=pending_calls,
            node_type="Function",
            outer_qualname=qualname,
        )

    return fn_id
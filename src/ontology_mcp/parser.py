from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from ontology_mcp.model import Edge, Node, OntologyGraph


# ---------------------------------------------------------------------------
# Noise filters
# ---------------------------------------------------------------------------

# Well-known external names that should NEVER be CALLS targets.
_EXTERNAL_CALL_NAMES: frozenset[str] = frozenset({
    # Python builtins — true for every Python project
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "list", "dict", "set", "tuple", "str", "int",
    "float", "bool", "bytes", "bytearray", "memoryview", "complex",
    "type", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "delattr", "vars", "dir", "open", "iter", "next", "super",
    "property", "staticmethod", "classmethod", "repr", "hash", "id",
    "abs", "round", "min", "max", "sum", "pow", "divmod",
    "any", "all", "callable", "format", "input", "exit", "quit",
    "exec", "eval", "compile", "globals", "locals", "object",
    "slice", "frozenset", "chr", "ord", "hex", "oct", "bin",
    "breakpoint",
    # Built-in exceptions — stdlib, always present
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "RuntimeError", "NotImplementedError",
    "OSError", "IOError", "FileNotFoundError", "PermissionError",
    "StopIteration", "GeneratorExit", "ArithmeticError", "ZeroDivisionError",
    "OverflowError", "MemoryError", "RecursionError", "SystemExit",
    "KeyboardInterrupt", "AssertionError", "ImportError", "ModuleNotFoundError",
    "NameError", "UnboundLocalError", "ReferenceError", "BufferError",
    "EOFError", "ConnectionError", "TimeoutError", "UnicodeError",
    "UnicodeDecodeError", "UnicodeEncodeError", "Warning", "UserWarning",
    "DeprecationWarning", "SyntaxError", "IndentationError",
})

# Nested class names that are pure metadata conventions in Python — skipped
# only when nested inside another class. Config and Meta are universal
_NOISE_NESTED_CLASS_NAMES: frozenset[str] = frozenset({"Config", "Meta"})

# ---------------------------------------------------------------------------
# Stable ID
# ---------------------------------------------------------------------------

def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#Function to get the base name of a node (for class bases and decorator names)
def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):   # Generic[T] → Generic
        return _base_name(node.value)
    return None

# Function to extract all nested statement lists from a compound statement (if/for/try/with/match)
def _child_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """All nested statement-lists inside a compound statement."""
    result: list[list[ast.stmt]] = []
    if isinstance(stmt, ast.If):
        result += [stmt.body, stmt.orelse]
    elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        result += [stmt.body, stmt.orelse]
    elif isinstance(stmt, ast.Try):
        result += [stmt.body, stmt.orelse, stmt.finalbody]
        result += [h.body for h in stmt.handlers]
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        result.append(stmt.body)
    elif hasattr(ast, "Match") and isinstance(stmt, ast.Match):
        result += [c.body for c in stmt.cases]
    return result

#Function to recursively collect all ClassDef and FunctionDef/AsyncFunctionDef nodes from a list of statements,
def _collect_class_and_func_nodes(
    body: list[ast.stmt],
) -> tuple[list[ast.ClassDef], list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    """
    Recursively extract ClassDef and FunctionDef/AsyncFunctionDef from any
    statement list, including those buried in if/try/with/for blocks.
    Does NOT descend into nested ClassDef bodies (handled separately).
    """
    classes: list[ast.ClassDef] = []
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for stmt in body:
        if isinstance(stmt, ast.ClassDef):
            classes.append(stmt)
        elif isinstance(stmt, _FUNC_TYPES):
            funcs.append(stmt)
        else:
            # Descend into any compound statements to find nested defs of class or function types
            for child in _child_bodies(stmt):
                sc, sf = _collect_class_and_func_nodes(child)
                classes.extend(sc)
                funcs.extend(sf)
    return classes, funcs

#Function to collect method definitions from a class body, including those behind compound statements
def _collect_methods(
    class_body: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """
    Collect method definitions from a class body, including those behind
    compound statements (if TYPE_CHECKING, etc.).
    Does NOT recurse into nested ClassDef bodies.
    """
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for stmt in class_body:
        if isinstance(stmt, _FUNC_TYPES):
            methods.append(stmt)
        elif not isinstance(stmt, ast.ClassDef):
            for child in _child_bodies(stmt):
                for s in child:
                    if isinstance(s, _FUNC_TYPES):
                        methods.append(s)
    return methods


# ---------------------------------------------------------------------------
# Import resolver
# Builds {local_name: rel_module_path} for every import in a file that
# resolves to a .py file inside the repo.
# Only intra-repo imports are tracked — external libs are ignored.
# ---------------------------------------------------------------------------

#Function to build an import map for a file, mapping local names to repo-relative paths based on the AST
def _build_import_map(
    tree: ast.Module,
    rel: str,
    repo_root: Path,
) -> dict[str, str]:
    import_map: dict[str, str] = {}
    file_dir = Path(rel).parent

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            candidates = _module_to_rel_paths(module, file_dir, repo_root)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname if alias.asname else alias.name
                for cand in candidates:
                    import_map[local_name] = cand
                    break

        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name.split(".")[0]
                candidates = _module_to_rel_paths(alias.name, file_dir, repo_root)
                for cand in candidates:
                    import_map[local_name] = cand
                    break

    return import_map

#Function to convert a dotted module name to candidate repo-relative file paths, checking for .py files and __init__.py in the repo
def _module_to_rel_paths(module: str, file_dir: Path, repo_root: Path) -> list[str]:
    """Convert a dotted module name to candidate repo-relative file paths."""
    if not module:
        return []
    rel_module = module.replace(".", "/")
    candidates = [
        rel_module,
        str(file_dir / rel_module).replace("\\", "/"),
    ]
    results = []
    for c in candidates:
        if (repo_root / (c + ".py")).exists():
            results.append(c)
        elif (repo_root / c / "__init__.py").exists():
            results.append(c + "/__init__")
    return results


# ---------------------------------------------------------------------------
# Call collector
# Collects (kind, name) pairs:
#   "name"  → bare call      foo()
#   "attr"  → attribute call  obj.foo()
# Does NOT descend into nested ClassDef bodies.
# ---------------------------------------------------------------------------

# AST visitor to collect function call sites within a function/method body, capturing both bare and attribute calls.
class _CallCollector(ast.NodeVisitor):

    # Initialize with an empty list to store collected calls as (kind, name) pairs.
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    # Visit a Call node in the AST, extract the function being called, and store it as a (kind, name) pair in self.calls.
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        if isinstance(func, ast.Name):
            self.calls.append(("name", func.id))
        elif isinstance(func, ast.Attribute):
            self.calls.append(("attr", func.attr))

        self.generic_visit(node)

    # Override visit_ClassDef to prevent descending into nested classes, which are handled separately in the main parser logic.
    def visit_ClassDef(self, node: ast.ClassDef) -> None:  
        pass  # do not descend into nested classes


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_python_files(repo_path: str, files: list[str]) -> OntologyGraph:
    repo_root = Path(repo_path).resolve()
    graph = OntologyGraph()

    repo_id = _stable_id("repo", str(repo_root))
    graph.add_node(Node(
        id=repo_id,
        type="Repository",
        properties={"id": repo_id, "name": repo_root.name, "path": str(repo_root)},
    ))

    # name → [(node_id, node_type)]
    # Stored as tuples so CALLS resolution can filter out Class nodes
    symbol_index: dict[str, list[tuple[str, str]]] = {}

    # class_name → [class_id]  for EXTENDS resolution
    class_index: dict[str, list[str]] = {}

    # (source_fn_id, import_map, [(kind, name)])
    pending_calls: list[tuple[str, dict[str, str], list[tuple[str, str]]]] = []

    # rel_path → file_id
    file_id_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Pass 1 — folder/file hierarchy + all symbol nodes
    # ------------------------------------------------------------------
    for fpath in files:
        fpath_obj = Path(fpath).resolve()
        rel = fpath_obj.relative_to(repo_root).as_posix()
        file_id = _stable_id("file", str(repo_root), rel)
        file_id_map[rel] = file_id

        graph.add_node(Node(
            id=file_id,
            type="File",
            properties={
                "id": file_id,
                "path": rel,
                "name": fpath_obj.name,
                "extension": ".py",
            },
        ))

        # Build folder chain
        parent = Path(rel).parent
        if str(parent) != ".":
            parts = parent.parts
            current = ""
            folder_ids: list[str] = []
            for part in parts:
                current = f"{current}/{part}" if current else part
                fid = _stable_id("folder", str(repo_root), current)
                folder_ids.append(fid)
                graph.add_node(Node(
                    id=fid,
                    type="Folder",
                    properties={"id": fid, "path": current, "name": part},
                ))
            graph.add_edge(Edge(repo_id, "CONTAINS", folder_ids[0]))
            for i in range(1, len(folder_ids)):
                graph.add_edge(Edge(folder_ids[i - 1], "CONTAINS", folder_ids[i]))
            graph.add_edge(Edge(folder_ids[-1], "CONTAINS", file_id))
        else:
            graph.add_edge(Edge(repo_id, "CONTAINS", file_id))

        # Parse
        text = _read_text(fpath)
        try:
            tree = ast.parse(text, filename=fpath)
        except SyntaxError as exc:
            graph.warnings.append(f"SyntaxError in {rel}: {exc}")
            continue

        import_map = _build_import_map(tree, rel, repo_root)

        top_classes, top_funcs = _collect_class_and_func_nodes(tree.body)

        for cls_node in top_classes:
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
                import_map=import_map,
            )

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
                import_map=import_map,
                node_type="Function",
            )

    # ------------------------------------------------------------------
    # Pass 2 — resolve EXTENDS
    # Rewire stub-target edges to real class nodes where possible.
    # Drop edges pointing at truly external classes (BaseModel, Base, etc.)
    # to avoid orphan stub nodes in the graph.
    # ------------------------------------------------------------------
    new_edges: list[Edge] = []
    for edge in graph.edges:
        if edge.rel_type != "EXTENDS":
            new_edges.append(edge)
            continue

        target = graph.nodes.get(edge.target_id)
        if target is None:
            continue

        # Already a real node — keep
        if not target.properties.get("external_ref"):
            new_edges.append(edge)
            continue

        # Stub — try to resolve to a real intra-repo class
        bname = target.properties.get("name", "")
        real_ids = class_index.get(bname, [])

        if not real_ids:
            # Truly external (BaseModel, Base, etc.) — drop stub + edge
            graph.nodes.pop(edge.target_id, None)
            continue

        if len(real_ids) == 1:
            new_edges.append(Edge(
                source_id=edge.source_id,
                rel_type="EXTENDS",
                target_id=real_ids[0],
                properties={"resolved": True},
            ))
        else:
            for rid in real_ids:
                new_edges.append(Edge(
                    source_id=edge.source_id,
                    rel_type="EXTENDS",
                    target_id=rid,
                    properties={"resolved": True, "confidence": "medium"},
                ))
        graph.nodes.pop(edge.target_id, None)  # remove stub

    graph.edges = new_edges

    # ------------------------------------------------------------------
    # Pass 3 — resolve CALLS
    # ------------------------------------------------------------------
    _resolve_calls(graph, symbol_index, pending_calls, file_id_map)

    return graph


# ---------------------------------------------------------------------------
# CALLS resolution
# ---------------------------------------------------------------------------

def _resolve_calls(
    graph: OntologyGraph,
    symbol_index: dict[str, list[tuple[str, str]]],
    pending_calls: list[tuple[str, dict[str, str], list[tuple[str, str]]]],
    file_id_map: dict[str, str],
) -> None:
    # node_id → file_id (to detect same-file calls)
    node_to_file: dict[str, str] = {}
    for node in graph.nodes.values():
        fp = node.properties.get("file_path")
        if fp and fp in file_id_map:
            node_to_file[node.id] = file_id_map[fp]

    for source_id, import_map, calls in pending_calls:
        caller_file_id = node_to_file.get(source_id)

        # Deduplicate calls within this function to avoid duplicate edges
        seen_targets: set[str] = set()

        for call_kind, call_name in calls:
            # Rule: skip known external names
            if call_name in _EXTERNAL_CALL_NAMES:
                continue

            candidates = symbol_index.get(call_name, [])
            if not candidates:
                continue

            # Rule: never CALLS → Class node (those are instantiations, not calls)
            fn_candidates = [
                (nid, ntype) for nid, ntype in candidates
                if ntype in ("Function", "Method")
            ]
            if not fn_candidates:
                continue

            # Rule: only emit cross-file CALLS if the name was explicitly
            # imported from within the repo in this file's import_map.
            # Same-file calls are always allowed.
            filtered: list[tuple[str, str]] = []
            for nid, ntype in fn_candidates:
                target_file = node_to_file.get(nid)
                if target_file == caller_file_id:
                    # Same file — always allow
                    filtered.append((nid, ntype))
                elif call_name in import_map:
                    # Cross-file — only if explicitly imported from repo
                    filtered.append((nid, ntype))

            if not filtered:
                continue

            confidence = "high" if len(filtered) == 1 else "medium"
            for nid, _ in filtered:
                if nid in seen_targets:
                    continue
                seen_targets.add(nid)
                graph.add_edge(Edge(
                    source_id=source_id,
                    rel_type="CALLS",
                    target_id=nid,
                    properties={"confidence": confidence, "kind": call_kind},
                ))


# ---------------------------------------------------------------------------
# Class processor
# ---------------------------------------------------------------------------

def _process_class(
    cls_node: ast.ClassDef,
    parent_id: str,
    file_id: str,
    rel: str,
    repo_root: Path,
    graph: OntologyGraph,
    symbol_index: dict[str, list[tuple[str, str]]],
    class_index: dict[str, list[str]],
    pending_calls: list[tuple[str, dict[str, str], list[tuple[str, str]]]],
    import_map: dict[str, str],
    outer_qualname: str = "",
) -> str:
    # Drop noise nested classes (Pydantic Config, Django Meta, etc.)
    if cls_node.name in _NOISE_NESTED_CLASS_NAMES and outer_qualname:
        return ""

    qualname = (
        f"{outer_qualname}.{cls_node.name}" if outer_qualname
        else f"{rel}:{cls_node.name}"
    )
    class_id = _stable_id("class", str(repo_root), qualname, str(cls_node.lineno))

    graph.add_node(Node(
        id=class_id,
        type="Class",
        properties={
            "id": class_id,
            "name": cls_node.name,
            "qualname": qualname,
            "file_path": rel,
            "lineno": cls_node.lineno,
        },
    ))

    # FIX 1 — CONTAINS not DEFINES for parent→class
    if parent_id == file_id:
        graph.add_edge(Edge(parent_id, "DEFINES", class_id))

    symbol_index.setdefault(cls_node.name, []).append((class_id, "Class"))
    class_index.setdefault(cls_node.name, []).append(class_id)

    # Base classes → EXTENDS via stub (resolved in pass 2)
    for base in cls_node.bases:
        bname = _base_name(base)
        if bname and bname != "object":
            stub_id = _stable_id("class_ref", str(repo_root), bname)
            if stub_id not in graph.nodes:
                graph.add_node(Node(
                    id=stub_id,
                    type="Class",
                    properties={
                        "id": stub_id,
                        "name": bname,
                        "qualname": bname,
                        "file_path": None,
                        "lineno": None,
                        "external_ref": True,
                    },
                ))
            graph.add_edge(Edge(class_id, "EXTENDS", stub_id))

    # Methods
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
            import_map=import_map,
            node_type="Method",
            outer_qualname=qualname,
            use_has_method=True,
        )

    # Nested classes (recursive)
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
                import_map=import_map,
                outer_qualname=qualname,
            )

    return class_id


# ---------------------------------------------------------------------------
# Function / Method processor
# ---------------------------------------------------------------------------

def _process_function(
    fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_id: str,
    file_id: str,
    rel: str,
    repo_root: Path,
    graph: OntologyGraph,
    symbol_index: dict[str, list[tuple[str, str]]],
    pending_calls: list[tuple[str, dict[str, str], list[tuple[str, str]]]],
    import_map: dict[str, str],
    node_type: str = "Function",
    outer_qualname: str = ""
) -> str:
    is_async = isinstance(fn_node, ast.AsyncFunctionDef)
    sep = "." if node_type == "Method" else ":"
    qualname = (
        f"{outer_qualname}{sep}{fn_node.name}" if outer_qualname
        else f"{rel}:{fn_node.name}"
    )
    prefix = "method" if node_type == "Method" else "function"
    fn_id = _stable_id(prefix, str(repo_root), qualname, str(fn_node.lineno))

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

    graph.add_node(Node(
        id=fn_id,
        type=node_type,
        properties={
            "id": fn_id,
            "name": fn_node.name,
            "qualname": qualname,
            "file_path": rel,
            "lineno": fn_node.lineno,
            "is_async": is_async,
            "decorators": ", ".join(decorator_names) if decorator_names else None,
        },
    ))

    # ✅ RELATION LOGIC (FINAL CLEAN)
    if node_type == "Method":
        # Class → Method
        graph.add_edge(Edge(parent_id, "CONTAINS", fn_id))

    elif parent_id == file_id:
        # File → Function (only top-level)
        graph.add_edge(Edge(parent_id, "DEFINES", fn_id))

    # ❌ No relation for nested functions (correct by design)

    symbol_index.setdefault(fn_node.name, []).append((fn_id, node_type))

    # Collect call sites
    collector = _CallCollector()
    collector.visit(fn_node)
    pending_calls.append((fn_id, import_map, collector.calls))

    # Nested functions
    _, inner_fns = _collect_class_and_func_nodes(fn_node.body)
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
            import_map=import_map,
            node_type="Function",
            outer_qualname=qualname,
        )

    return fn_id
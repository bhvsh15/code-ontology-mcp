"""
Tree-sitter based multi-language source file parser.

Extracts structural entities (classes, functions, methods, imports) and
relationships (DEFINES, CONTAINS, IMPORTS, CALLS) from non-Python files
and adds them to an ``OntologyGraph`` in the same format as the Python
AST parser.

Supported languages
-------------------
javascript  .js .jsx .mjs
typescript  .ts
tsx         .tsx
csharp      .cs
go          .go
rust        .rs

How it works
------------
1. ``parse_file`` is called once per file with the already-created File
   node id so the parser can attach DEFINES / CONTAINS edges to it.
2. ``_walk`` recursively descends the tree-sitter CST, matching node
   types from the per-language lookup tables (_CLASS_TYPES, etc.).
3. ``_extract_calls`` walks inside each function node to collect call
   sites, creating lightweight placeholder nodes for unresolved targets
   (``external_ref=True``).

Limitations
-----------
- Call resolution is name-based only (no type inference).  ``obj.method()``
  resolves to ``"method"`` regardless of ``obj``'s type.
- Cross-file CALLS edges are not resolved here; the graph writer
  deduplicates and links by name when queries traverse the graph.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ontology_mcp.model import Edge, Node, OntologyGraph

# ---------------------------------------------------------------------------
# Language → file extensions
# ---------------------------------------------------------------------------

LANG_EXTENSIONS: dict[str, list[str]] = {
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts"],
    "tsx":        [".tsx"],
    "csharp":     [".cs"],
    "go":         [".go"],
    "rust":       [".rs"],
}

EXT_TO_LANG: dict[str, str] = {
    ext: lang for lang, exts in LANG_EXTENSIONS.items() for ext in exts
}

# ---------------------------------------------------------------------------
# Tree-sitter node types we care about, per language
# ---------------------------------------------------------------------------

_CLASS_TYPES: dict[str, list[str]] = {
    "javascript": ["class_declaration", "class"],
    "typescript": ["class_declaration", "class"],
    "tsx":        ["class_declaration", "class"],
    "csharp":     ["class_declaration", "interface_declaration",
                   "enum_declaration", "struct_declaration"],
    "go":         ["type_declaration"],
    "rust":       ["struct_item", "enum_item", "impl_item"],
}

_FUNCTION_TYPES: dict[str, list[str]] = {
    "javascript": ["function_declaration", "method_definition", "arrow_function"],
    "typescript": ["function_declaration", "method_definition", "arrow_function"],
    "tsx":        ["function_declaration", "method_definition", "arrow_function"],
    "csharp":     ["method_declaration", "constructor_declaration",
                   "local_function_statement"],
    "go":         ["function_declaration", "method_declaration"],
    "rust":       ["function_item"],
}

_IMPORT_TYPES: dict[str, list[str]] = {
    "javascript": ["import_statement"],
    "typescript": ["import_statement"],
    "tsx":        ["import_statement"],
    "csharp":     ["using_directive"],
    "go":         ["import_declaration"],
    "rust":       ["use_declaration"],
}

_CALL_TYPES: dict[str, list[str]] = {
    "javascript": ["call_expression", "new_expression"],
    "typescript": ["call_expression", "new_expression"],
    "tsx":        ["call_expression", "new_expression"],
    "csharp":     ["invocation_expression", "object_creation_expression"],
    "go":         ["call_expression"],
    "rust":       ["call_expression", "macro_invocation"],
}

# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Name extractors per language
# ---------------------------------------------------------------------------

def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_text(node: Any, field: str, source: bytes) -> str | None:
    child = node.child_by_field_name(field)
    return _text(child, source) if child else None


def _get_name(node: Any, language: str, source: bytes) -> str | None:
    """Extract the declaration name from a node."""
    # Most languages use a "name" field
    name_node = node.child_by_field_name("name")
    if name_node:
        return _text(name_node, source).strip()

    # Go type_declaration wraps a type_spec with a "name" field
    if language == "go" and node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                n = child.child_by_field_name("name")
                if n:
                    return _text(n, source).strip()

    # Rust impl_item: use the type name, not "impl"
    if language == "rust" and node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node:
            return _text(type_node, source).strip()

    # Arrow functions are often anonymous — skip
    return None


def _get_call_name(node: Any, language: str, source: bytes) -> str | None:
    """Extract the called function/method name from a call node."""
    if language in ("javascript", "typescript", "tsx", "go", "csharp"):
        fn = node.child_by_field_name("function")
        if fn:
            # member access: foo.bar() → "bar"
            attr = fn.child_by_field_name("property") or fn.child_by_field_name("field")
            if attr:
                return _text(attr, source).strip()
            return _text(fn, source).strip().split(".")[-1]

    if language == "rust":
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn:
                return _text(fn, source).strip().split("::")[-1]
        elif node.type == "macro_invocation":
            macro = node.child_by_field_name("macro")
            if macro:
                return _text(macro, source).strip() + "!"

    return None


def _get_import_path(node: Any, language: str, source: bytes) -> str | None:
    """Extract the import module/path string."""
    if language in ("javascript", "typescript", "tsx"):
        src_node = node.child_by_field_name("source")
        if src_node:
            return _text(src_node, source).strip().strip("'\"")

    if language == "csharp":
        # using_directive: "using" + name
        for child in node.children:
            if child.type in ("qualified_name", "identifier"):
                return _text(child, source).strip()

    if language == "go":
        # import_declaration may contain import_spec_list or single import_spec
        for child in node.children:
            if child.type in ("import_spec_list", "import_spec"):
                for spec in (child.children if child.type == "import_spec_list" else [child]):
                    path_node = spec.child_by_field_name("path")
                    if path_node:
                        return _text(path_node, source).strip().strip('"')

    if language == "rust":
        # use_declaration has a "argument" field
        arg = node.child_by_field_name("argument")
        if arg:
            return _text(arg, source).strip()

    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def _get_parser(language: str):
    try:
        import tree_sitter_language_pack as tslp
        return tslp.get_parser(language)
    except (LookupError, ValueError, ImportError, Exception):
        return None


def parse_file(
    file_path: str,
    repo_root: str,
    graph: OntologyGraph,
    file_node_id: str,
) -> None:
    """
    Parse a single non-Python source file using tree-sitter and add
    nodes/edges to the provided graph.
    """
    path = Path(file_path)
    language = EXT_TO_LANG.get(path.suffix.lower())
    if not language:
        return

    parser = _get_parser(language)
    if not parser:
        return

    try:
        source = path.read_bytes()
    except OSError:
        return

    tree = parser.parse(source)
    root_node = tree.root_node
    rel_path = path.relative_to(repo_root).as_posix()

    _walk(root_node, language, source, rel_path, repo_root,
          graph, file_node_id, parent_class_id=None, parent_class_name=None)


def _walk(
    node: Any,
    language: str,
    source: bytes,
    rel_path: str,
    repo_root: str,
    graph: OntologyGraph,
    file_node_id: str,
    parent_class_id: str | None,
    parent_class_name: str | None,
) -> None:
    node_type = node.type
    class_types = _CLASS_TYPES.get(language, [])
    func_types = _FUNCTION_TYPES.get(language, [])
    import_types = _IMPORT_TYPES.get(language, [])
    call_types = _CALL_TYPES.get(language, [])

    # --- Class / struct / interface ---
    if node_type in class_types:
        name = _get_name(node, language, source)
        if name:
            qualname = f"{rel_path}:{name}"
            nid = _stable_id("class", repo_root, qualname, str(node.start_point[0]))
            graph.add_node(Node(
                id=nid,
                type="Class",
                properties={
                    "id": nid,
                    "name": name,
                    "qualname": qualname,
                    "file_path": rel_path,
                    "lineno": node.start_point[0] + 1,
                    "language": language,
                },
            ))
            graph.add_edge(Edge(file_node_id, "DEFINES", nid))

            # Recurse into class body with this class as parent
            for child in node.children:
                _walk(child, language, source, rel_path, repo_root,
                      graph, file_node_id, nid, name)
            return

    # --- Function / method ---
    if node_type in func_types:
        name = _get_name(node, language, source)
        if name:
            is_method = parent_class_id is not None
            qualname = (
                f"{rel_path}:{parent_class_name}.{name}"
                if is_method else f"{rel_path}:{name}"
            )
            prefix = "method" if is_method else "function"
            nid = _stable_id(prefix, repo_root, qualname, str(node.start_point[0]))
            node_type_label = "Method" if is_method else "Function"

            graph.add_node(Node(
                id=nid,
                type=node_type_label,
                properties={
                    "id": nid,
                    "name": name,
                    "qualname": qualname,
                    "file_path": rel_path,
                    "lineno": node.start_point[0] + 1,
                    "language": language,
                },
            ))

            if is_method:
                graph.add_edge(Edge(parent_class_id, "CONTAINS", nid))
            else:
                graph.add_edge(Edge(file_node_id, "DEFINES", nid))

            # Extract calls inside this function
            _extract_calls(node, language, source, rel_path, repo_root,
                           graph, nid)

    # --- Import ---
    elif node_type in import_types:
        module = _get_import_path(node, language, source)
        if module:
            imp_id = _stable_id("import", rel_path, module)
            if imp_id not in graph.nodes:
                graph.add_node(Node(
                    id=imp_id,
                    type="Import",
                    properties={
                        "id": imp_id,
                        "name": module,
                        "file_path": rel_path,
                        "language": language,
                    },
                ))
            graph.add_edge(Edge(file_node_id, "IMPORTS", imp_id))

    # Recurse for non-class, non-function nodes
    if node_type not in class_types and node_type not in func_types:
        for child in node.children:
            _walk(child, language, source, rel_path, repo_root,
                  graph, file_node_id, parent_class_id, parent_class_name)


def _extract_calls(
    fn_node: Any,
    language: str,
    source: bytes,
    rel_path: str,
    repo_root: str,
    graph: OntologyGraph,
    caller_id: str,
) -> None:
    """Walk a function node and collect all call expressions."""
    call_types = _CALL_TYPES.get(language, [])

    def _visit(node: Any) -> None:
        if node.type in call_types:
            callee = _get_call_name(node, language, source)
            if callee and len(callee) > 1:
                target_id = _stable_id("call-target", rel_path, callee)
                if target_id not in graph.nodes:
                    graph.add_node(Node(
                        id=target_id,
                        type="Function",
                        properties={
                            "id": target_id,
                            "name": callee,
                            "qualname": callee,
                            "file_path": None,
                            "external_ref": True,
                            "language": language,
                        },
                    ))
                graph.add_edge(Edge(caller_id, "CALLS", target_id))
        for child in node.children:
            _visit(child)

    _visit(fn_node)
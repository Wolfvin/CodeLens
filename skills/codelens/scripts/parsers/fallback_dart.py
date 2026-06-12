"""Fallback Dart parser for CodeLens.

Extracts structural information from Dart source files using regex.
Used when tree-sitter Dart grammar is not available.

Dart is the primary language for Flutter apps and can also be used
for server-side development.

Extracts:
- import declarations
- class declarations (with inheritance)
- mixin declarations
- enum declarations
- function/method declarations
- top-level variables and constants
"""

import re
from typing import Dict, List, Any


def parse_dart_fallback(content: str, file_path: str = "") -> Dict[str, Any]:
    """Parse Dart source file using regex-based fallback.

    Args:
        content: Dart source code content
        file_path: Relative file path for reference

    Returns:
        Dict with nodes (functions, classes, enums, mixins) and edges (imports, calls).
    """
    nodes = []
    edges = []

    # ─── Imports ─────────────────────────────────────────────
    for m in re.finditer(r'''import\s+['"]([^'"]+)['"]''', content):
        import_path = m.group(1)
        edges.append({
            "from": f"{file_path}::(module)",
            "to": import_path,
            "to_fn": import_path,
            "type": "import",
            "line": content[:m.start()].count('\n') + 1
        })

    # Also detect 'part' directives
    for m in re.finditer(r'''part\s+['"]([^'"]+)['"]''', content):
        import_path = m.group(1)
        edges.append({
            "from": f"{file_path}::(module)",
            "to": import_path,
            "to_fn": import_path,
            "type": "part",
            "line": content[:m.start()].count('\n') + 1
        })

    # ─── Class declarations ──────────────────────────────────
    # Pattern: (abstract)? class Name (extends Parent)? (implements Interface1, Interface2)? (with Mixin1, Mixin2)?
    for m in re.finditer(
        r'(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+with\s+([\w,\s]+))?(?:\s+implements\s+([\w,\s]+))?\s*\{',
        content
    ):
        class_name = m.group(1)
        parent_class = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        node = {
            "id": f"{file_path}::{class_name}",
            "name": class_name,
            "fn": class_name,
            "file": file_path,
            "line": line_num,
            "type": "class",
            "ref_count": 0,
            "status": "active"
        }
        if parent_class:
            node["extends"] = parent_class
            edges.append({
                "from": f"{file_path}::{class_name}",
                "to": parent_class,
                "type": "extends",
                "line": line_num
            })
        nodes.append(node)

    # ─── Mixin declarations ──────────────────────────────────
    for m in re.finditer(r'mixin\s+(\w+)(?:\s+on\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?\s*\{', content):
        mixin_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{file_path}::{mixin_name}",
            "name": mixin_name,
            "fn": mixin_name,
            "file": file_path,
            "line": line_num,
            "type": "mixin",
            "ref_count": 0,
            "status": "active"
        })

    # ─── Enum declarations ───────────────────────────────────
    for m in re.finditer(r'enum\s+(\w+)\s*\{', content):
        enum_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{file_path}::{enum_name}",
            "name": enum_name,
            "fn": enum_name,
            "file": file_path,
            "line": line_num,
            "type": "enum",
            "ref_count": 0,
            "status": "active"
        })

    # ─── Extension declarations ──────────────────────────────
    for m in re.finditer(r'extension\s+(\w+)\s+on\s+(\w+)\s*\{', content):
        ext_name = m.group(1)
        on_type = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{file_path}::{ext_name}",
            "name": ext_name,
            "fn": ext_name,
            "file": file_path,
            "line": line_num,
            "type": "extension",
            "on": on_type,
            "ref_count": 0,
            "status": "active"
        })

    # ─── Function declarations ───────────────────────────────
    # Top-level functions and methods
    # Pattern: (static)? (async)? ReturnType? functionName(params) { or =>
    for m in re.finditer(
        r'''(?:(?:static|abstract|external|factory)\s+)?  # modifiers
        (?:async\s+)?
        (?:[\w<>\[\]?]+\s+)?  # optional return type
        ([a-z_]\w*)\s*  # function name (must start with lowercase)
        \(([^)]*)\)\s*  # parameters
        (?:async\s*)?
        (?:\{|=>)  # body start
        ''',
        content, re.VERBOSE
    ):
        func_name = m.group(1)
        params = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Skip keywords and common false positives
        if func_name in ('if', 'else', 'while', 'for', 'switch', 'catch', 'return',
                        'class', 'enum', 'mixin', 'extension', 'import', 'export',
                        'part', 'typedef', 'get', 'set', 'operator', 'void',
                        'var', 'final', 'const', 'late', 'required', 'covariant',
                        'show', 'hide', 'as', 'on', 'is', 'in', 'new', 'super',
                        'this', 'throw', 'try', 'do', 'assert', 'yield', 'await'):
            continue

        # Determine if it's a method (inside a class) or top-level
        node = {
            "id": f"{file_path}::{func_name}",
            "name": func_name,
            "fn": func_name,
            "file": file_path,
            "line": line_num,
            "type": "method",  # Default; scan.py will set correct scope
            "ref_count": 0,
            "status": "active"
        }
        if params.strip():
            node["params"] = params.strip()
        nodes.append(node)

    # ─── Getter/Setter declarations ──────────────────────────
    for m in re.finditer(r'(?:static\s+)?(?:get|set)\s+(\w+)\s*(?:\([^)]*\))?\s*(?:\{|=>)', content):
        prop_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        is_getter = 'get ' in content[m.start():m.start()+30]
        nodes.append({
            "id": f"{file_path}::{prop_name}_{'getter' if is_getter else 'setter'}",
            "name": prop_name,
            "fn": f"{'get' if is_getter else 'set'} {prop_name}",
            "file": file_path,
            "line": line_num,
            "type": "property_accessor",
            "ref_count": 0,
            "status": "active"
        })

    # ─── Top-level constants ─────────────────────────────────
    for m in re.finditer(r'^\s*const\s+([A-Za-z_]\w*)\s*=', content, re.MULTILINE):
        const_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{file_path}::{const_name}",
            "name": const_name,
            "fn": const_name,
            "file": file_path,
            "line": line_num,
            "type": "constant",
            "ref_count": 0,
            "status": "active"
        })

    return {
        "nodes": nodes,
        "edges": edges
    }

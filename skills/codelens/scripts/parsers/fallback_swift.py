"""
Fallback Swift Parser for CodeLens — regex-based extraction.
Extracts classes, structs, protocols, extensions, enums, SwiftUI patterns,
and function call relationships for edge resolution.
Supports: class, struct, protocol, extension, enum, actor,
          func, var, let, SwiftUI View patterns, async/await, etc.
"""

import re
from typing import Dict, List, Any


def parse_swift_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Swift source using regex — extracts classes, structs, functions, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Imports — module-level dependency edges
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*import\s+([\w]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "import", "weight": 1})

    # Collect definitions
    fn_defs = {}  # fn_name → node_id
    type_defs = {}  # type_name → node_id

    # Types: class, struct, protocol, extension, enum, actor
    for i, line in enumerate(lines, 1):
        # actor (Swift concurrency)
        m = re.match(r'\s*actor\s+(\w+)', line)
        if m:
            name = m.group(1)
            node_id = f"{rel_path}:{i}:{name}"
            nodes.append({"id": node_id, "type": "actor",
                          "name": name, "fn": name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[name] = node_id
            continue
        # class (possibly final, open, public, etc.)
        m = re.match(r'\s*(?:final\s+|open\s+|public\s+|private\s+|internal\s+)*(?:class)\s+(\w+)', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}"
            ntype = "class"
            # Detect SwiftUI types
            if 'ObservableObject' in line:
                ntype = "observable_object"
            elif 'UIViewController' in line or 'UIApplicationDelegate' in line:
                ntype = "ui_class"
            nodes.append({"id": node_id, "type": ntype,
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[cls_name] = node_id
            # Check inheritance
            m2 = re.search(r':\s*(\w+)', line)
            if m2:
                parent = m2.group(1)
                if parent not in ('Codable', 'Hashable', 'Equatable', 'Identifiable',
                                  'Observable', 'Sendable'):
                    edges.append({"from": node_id, "to_fn": parent, "type": "inherits", "weight": 1})
            continue
        # struct
        m = re.match(r'\s*(?:public\s+|private\s+|internal\s+)*struct\s+(\w+)', line)
        if m:
            struct_name = m.group(1)
            node_id = f"{rel_path}:{i}:{struct_name}"
            ntype = "struct"
            if 'View' in line and 'protocol' not in line:
                ntype = "swiftui_view"
            nodes.append({"id": node_id, "type": ntype,
                          "name": struct_name, "fn": struct_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[struct_name] = node_id
            continue
        # protocol
        m = re.match(r'\s*(?:public\s+|private\s+)*protocol\s+(\w+)', line)
        if m:
            proto_name = m.group(1)
            node_id = f"{rel_path}:{i}:{proto_name}"
            nodes.append({"id": node_id, "type": "protocol",
                          "name": proto_name, "fn": proto_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[proto_name] = node_id
            continue
        # extension
        m = re.match(r'\s*extension\s+(\w+)', line)
        if m:
            ext_on = m.group(1)
            node_id = f"{rel_path}:{i}:ext_{ext_on}"
            nodes.append({"id": node_id, "type": "extension",
                          "name": f"Extension on {ext_on}", "fn": ext_on,
                          "file": rel_path, "line": i, "domain": "backend",
                          "extends": ext_on})
            continue
        # enum
        m = re.match(r'\s*(?:public\s+|private\s+|indirect\s+)*enum\s+(\w+)', line)
        if m:
            enum_name = m.group(1)
            node_id = f"{rel_path}:{i}:{enum_name}"
            ntype = "enum"
            if 'Error' in line:
                ntype = "error_enum"
            nodes.append({"id": node_id, "type": ntype,
                          "name": enum_name, "fn": enum_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[enum_name] = node_id
            continue
        # typealias
        m = re.match(r'\s*typealias\s+(\w+)', line)
        if m:
            ta_name = m.group(1)
            node_id = f"{rel_path}:{i}:{ta_name}"
            nodes.append({"id": node_id, "type": "typealias",
                          "name": ta_name, "fn": ta_name,
                          "file": rel_path, "line": i, "domain": "backend"})

    # Functions and properties
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # func declarations (instance, static, class)
        m = re.match(r'\s*(?:static\s+|class\s+|override\s+|public\s+|private\s+|internal\s+|open\s+|@[\w]+\s+)*(?:func|init|deinit)\s+(\w+)?\s*[\(<]', line)
        if not m:
            # init without name
            m2 = re.match(r'\s*(?:public\s+|private\s+|override\s+)*init\s*[\(<]', line)
            if m2:
                node_id = f"{rel_path}:{i}:init"
                nodes.append({"id": node_id, "type": "constructor",
                              "name": "init", "fn": "init",
                              "file": rel_path, "line": i, "domain": "backend"})
                fn_defs["init"] = node_id
                continue
            continue
        fn_name = m.group(1) or "init"
        # Skip keywords
        if fn_name in ('if', 'else', 'while', 'for', 'switch', 'return', 'class', 'struct'):
            continue
        node_id = f"{rel_path}:{i}:{fn_name}"
        ntype = "function"
        if fn_name == "init":
            ntype = "constructor"
        elif fn_name == "main":
            ntype = "entry_point"
        elif fn_name.startswith("test") or "test" in line.lower():
            ntype = "test"
        elif fn_name == "body":
            ntype = "computed_property"
        nodes.append({"id": node_id, "type": ntype,
                      "name": fn_name, "fn": fn_name,
                      "file": rel_path, "line": i, "domain": "backend"})
        fn_defs[fn_name] = node_id
        continue

    # ─── Function call edges ─────────────────────────────────────
    _SWIFT_KEYWORDS = frozenset({
        'if', 'else', 'while', 'for', 'switch', 'case', 'return', 'break',
        'continue', 'class', 'struct', 'protocol', 'extension', 'enum',
        'func', 'var', 'let', 'import', 'guard', 'defer', 'do', 'try',
        'catch', 'throw', 'nil', 'true', 'false', 'self', 'super',
        'init', 'deinit', 'typealias', 'as', 'is', 'in', 'where',
        'associatedtype', 'subscript', 'operator', 'precedencegroup',
        'inout', 'mutating', 'nonmutating', 'override', 'static', 'class',
        'convenience', 'required', 'dynamic', 'lazy', 'weak', 'unowned',
        'open', 'fileprivate', 'internal', 'public', 'private', 'set', 'get',
        'willSet', 'didSet', 'some', 'any', 'async', 'await', 'MainActor',
        'print', 'assert', 'precondition', 'fatalError',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0
    brace_count = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("function", "constructor", "entry_point", "test"):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn:
            stripped = line.strip()
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0 and i > fn_start:
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    call_pattern = re.compile(r'([\w]+)\.([\w]+)\s*\(')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            obj = m.group(1)
            method = m.group(2)
            if obj in _SWIFT_KEYWORDS or method in _SWIFT_KEYWORDS:
                continue
            full_name = f"{obj}.{method}"
            if method in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[method],
                    "to_fn": method,
                    "type": "call",
                    "weight": 1,
                })
            else:
                edges.append({
                    "from": fn_id,
                    "to_fn": full_name,
                    "type": "call",
                    "weight": 1,
                })
        # Simple function calls
        simple_call = re.compile(r'(?<!\.)([\w]+)\s*\(')
        for m in simple_call.finditer(body):
            fn_name = m.group(1)
            if fn_name in _SWIFT_KEYWORDS:
                continue
            if fn_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[fn_name],
                    "to_fn": fn_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}

"""
Fallback Dart Parser for CodeLens — regex-based extraction.
Extracts classes, mixins, extensions, functions, enums, Flutter patterns,
and method call relationships for edge resolution.
Supports: class, abstract class, mixin, extension, enum, typedef,
          factory constructors, StatefulWidget, StatelessWidget, etc.
"""

import re
from typing import Dict, List, Any


def parse_dart_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Dart source using regex — extracts classes, functions, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Imports — module-level import edges
    for i, line in enumerate(lines, 1):
        m = re.match(r"\s*import\s+['\"]([^'\"]+)['\"]", line)
        if m:
            import_path = m.group(1)
            edges.append({"from": rel_path, "to": import_path, "type": "import", "weight": 1})
            continue
        m = re.match(r"\s*export\s+['\"]([^'\"]+)['\"]", line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "export", "weight": 1})
            continue
        m = re.match(r"\s*part\s+['\"]([^'\"]+)['\"]", line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "part", "weight": 1})

    # Collect definitions
    fn_defs = {}  # fn_name → node_id
    class_defs = {}  # class_name → node_id

    # Classes (including abstract, with generics)
    for i, line in enumerate(lines, 1):
        # abstract class
        m = re.match(r'\s*abstract\s+class\s+(\w+)', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}"
            nodes.append({"id": node_id, "type": "abstract_class",
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            class_defs[cls_name] = node_id
            # Check extends/implements
            m2 = re.search(r'\s+extends\s+(\w+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "extends", "weight": 1})
            m3 = re.search(r'\s+implements\s+([\w,\s]+)', line)
            if m3:
                for impl in re.findall(r'(\w+)', m3.group(1)):
                    if impl not in ('extends', 'implements', 'with'):
                        edges.append({"from": node_id, "to_fn": impl, "type": "implements", "weight": 1})
            m4 = re.search(r'\s+with\s+([\w,\s]+)', line)
            if m4:
                for mixin in re.findall(r'(\w+)', m4.group(1)):
                    if mixin not in ('extends', 'implements', 'with'):
                        edges.append({"from": node_id, "to_fn": mixin, "type": "mixin", "weight": 1})
            continue
        # class
        m = re.match(r'\s*class\s+(\w+)', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}"
            ntype = "class"
            # Detect Flutter widget types
            if 'StatefulWidget' in line:
                ntype = "stateful_widget"
            elif 'StatelessWidget' in line:
                ntype = "stateless_widget"
            nodes.append({"id": node_id, "type": ntype,
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            class_defs[cls_name] = node_id
            # Check extends/implements/with
            m2 = re.search(r'\s+extends\s+(\w+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "extends", "weight": 1})
            m3 = re.search(r'\s+implements\s+([\w,\s]+)', line)
            if m3:
                for impl in re.findall(r'(\w+)', m3.group(1)):
                    if impl not in ('extends', 'implements', 'with'):
                        edges.append({"from": node_id, "to_fn": impl, "type": "implements", "weight": 1})
            m4 = re.search(r'\s+with\s+([\w,\s]+)', line)
            if m4:
                for mixin in re.findall(r'(\w+)', m4.group(1)):
                    if mixin not in ('extends', 'implements', 'with'):
                        edges.append({"from": node_id, "to_fn": mixin, "type": "mixin", "weight": 1})
            continue
        # mixin
        m = re.match(r'\s*mixin\s+(\w+)', line)
        if m:
            mixin_name = m.group(1)
            node_id = f"{rel_path}:{i}:{mixin_name}"
            nodes.append({"id": node_id, "type": "mixin",
                          "name": mixin_name, "fn": mixin_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            class_defs[mixin_name] = node_id
            continue
        # extension
        m = re.match(r'\s*extension\s+(\w+)\s+on\s+(\w+)', line)
        if m:
            ext_name = m.group(1)
            on_type = m.group(2)
            node_id = f"{rel_path}:{i}:{ext_name}"
            nodes.append({"id": node_id, "type": "extension",
                          "name": ext_name, "fn": ext_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "on_type": on_type})
            continue
        # enum
        m = re.match(r'\s*enum\s+(\w+)', line)
        if m:
            enum_name = m.group(1)
            node_id = f"{rel_path}:{i}:{enum_name}"
            nodes.append({"id": node_id, "type": "enum",
                          "name": enum_name, "fn": enum_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # typedef
        m = re.match(r'\s*typedef\s+(\w+)', line)
        if m:
            td_name = m.group(1)
            node_id = f"{rel_path}:{i}:{td_name}"
            nodes.append({"id": node_id, "type": "typedef",
                          "name": td_name, "fn": td_name,
                          "file": rel_path, "line": i, "domain": "backend"})

    # Methods and functions
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Constructor: ClassName() or ClassName.named()
        m = re.match(r'\s*(\w+)\.([\w]+)\s*\(', line)
        if m:
            cls_name = m.group(1)
            named_con = m.group(2)
            if cls_name in class_defs:
                node_id = f"{rel_path}:{i}:{cls_name}.{named_con}"
                nodes.append({"id": node_id, "type": "constructor",
                              "name": f"{cls_name}.{named_con}", "fn": named_con,
                              "file": rel_path, "line": i, "domain": "backend",
                              "class": cls_name})
                fn_defs[named_con] = node_id
                continue
        # Default constructor: ClassName(
        m = re.match(r'\s*(\w+)\s*\(', line)
        if m and m.group(1) in class_defs:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}.constructor"
            nodes.append({"id": node_id, "type": "constructor",
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "class": cls_name})
            fn_defs[cls_name] = node_id
            continue
        # factory constructor
        m = re.match(r'\s*factory\s+(\w+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:factory_{fn_name}"
            nodes.append({"id": node_id, "type": "factory",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue
        # Regular method/function with optional async
        m = re.match(r'\s*(?:static\s+)?(?:async\s+)?(?:[\w<>\[\]?]+\s+)?(\w+)\s*\(', line)
        if m:
            fn_name = m.group(1)
            # Skip Dart keywords
            if fn_name in ('if', 'else', 'while', 'for', 'switch', 'case', 'return',
                           'class', 'abstract', 'mixin', 'extension', 'enum', 'typedef',
                           'import', 'export', 'part', 'library', 'new', 'this', 'super',
                           'throw', 'try', 'catch', 'finally', 'on', 'is', 'as', 'in',
                           'get', 'set', 'operator', 'void', 'var', 'final', 'const',
                           'late', 'required', 'covariant', 'dynamic'):
                continue
            # Skip if already defined as class
            if fn_name in class_defs:
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            ntype = "method"
            if fn_name == "main":
                ntype = "entry_point"
            elif fn_name == "build":
                ntype = "build_method"
            elif fn_name.startswith("test"):
                ntype = "test"
            elif fn_name.startswith("_"):
                ntype = "private_method"
            nodes.append({"id": node_id, "type": ntype,
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue
        # Override annotation
        m = re.match(r'\s*@override', line)
        if m:
            continue  # Annotation, skip

    # ─── Method call edges ─────────────────────────────────────
    _DART_KEYWORDS = frozenset({
        'if', 'else', 'while', 'for', 'switch', 'case', 'return',
        'class', 'abstract', 'mixin', 'extension', 'enum', 'typedef',
        'import', 'export', 'part', 'library', 'new', 'this', 'super',
        'throw', 'try', 'catch', 'finally', 'on', 'is', 'as', 'in',
        'get', 'set', 'operator', 'void', 'var', 'final', 'const',
        'late', 'required', 'covariant', 'dynamic', 'async', 'await',
        'yield', 'sync', 'true', 'false', 'null', 'print',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0
    brace_count = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("method", "entry_point", "build_method",
                                                                "constructor", "factory", "private_method"):
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

    # Extract calls from each method body
    call_pattern = re.compile(r'([\w]+)\.([\w]+)\s*\(')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            obj = m.group(1)
            method = m.group(2)
            if obj in _DART_KEYWORDS or method in _DART_KEYWORDS:
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
        # Also check simple function calls
        simple_call = re.compile(r'(?<!\.)([\w]+)\s*\(')
        for m in simple_call.finditer(body):
            fn_name = m.group(1)
            if fn_name in _DART_KEYWORDS:
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

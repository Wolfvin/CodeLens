"""
Fallback Scala Parser for CodeLens — regex-based extraction.
Extracts classes, objects, traits, case classes, functions, Spark patterns,
and method call relationships for edge resolution.
Supports: class, object, trait, case class, sealed trait, def, val, var,
          implicit, package, import, extension methods, etc.
"""

import re
from typing import Dict, List, Any


def parse_scala_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Scala source using regex — extracts classes, objects, functions, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Package and imports
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*package\s+([\w.]+)', line)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:package_{m.group(1)}", "type": "package",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.match(r'\s*import\s+([\w.{*}]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "import", "weight": 1})

    # Collect definitions
    fn_defs = {}
    type_defs = {}

    # Types: class, object, trait, case class, sealed trait/class
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # sealed trait/class
        m = re.match(r'\s*sealed\s+(trait|class)\s+(\w+)', line)
        if m:
            kind = m.group(1)
            name = m.group(2)
            node_id = f"{rel_path}:{i}:{name}"
            ntype = "sealed_trait" if kind == "trait" else "sealed_class"
            nodes.append({"id": node_id, "type": ntype,
                          "name": name, "fn": name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[name] = node_id
            # Check extends
            m2 = re.search(r'\s+extends\s+([\w.]+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "inherits", "weight": 1})
            continue
        # case class
        m = re.match(r'\s*case\s+class\s+(\w+)', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}"
            nodes.append({"id": node_id, "type": "case_class",
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[cls_name] = node_id
            m2 = re.search(r'\s+extends\s+([\w.]+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "inherits", "weight": 1})
            continue
        # trait
        m = re.match(r'\s*trait\s+(\w+)', line)
        if m:
            trait_name = m.group(1)
            node_id = f"{rel_path}:{i}:{trait_name}"
            nodes.append({"id": node_id, "type": "trait",
                          "name": trait_name, "fn": trait_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[trait_name] = node_id
            continue
        # object (companion or standalone)
        m = re.match(r'\s*(?:case\s+)?object\s+(\w+)', line)
        if m:
            obj_name = m.group(1)
            node_id = f"{rel_path}:{i}:{obj_name}"
            nodes.append({"id": node_id, "type": "object",
                          "name": obj_name, "fn": obj_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[obj_name] = node_id
            m2 = re.search(r'\s+extends\s+([\w.]+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "inherits", "weight": 1})
            continue
        # class (abstract or regular)
        m = re.match(r'\s*(?:abstract\s+)?class\s+(\w+)', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:{cls_name}"
            ntype = "abstract_class" if 'abstract' in line else "class"
            nodes.append({"id": node_id, "type": ntype,
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[cls_name] = node_id
            m2 = re.search(r'\s+extends\s+([\w.]+)', line)
            if m2:
                edges.append({"from": node_id, "to_fn": m2.group(1), "type": "inherits", "weight": 1})
            continue
        # enum (Scala 3)
        m = re.match(r'\s*enum\s+(\w+)', line)
        if m:
            enum_name = m.group(1)
            node_id = f"{rel_path}:{i}:{enum_name}"
            nodes.append({"id": node_id, "type": "enum",
                          "name": enum_name, "fn": enum_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            type_defs[enum_name] = node_id
            continue
        # type alias
        m = re.match(r'\s*type\s+(\w+)\s*=', line)
        if m:
            type_name = m.group(1)
            node_id = f"{rel_path}:{i}:type_{type_name}"
            nodes.append({"id": node_id, "type": "type_alias",
                          "name": type_name, "fn": type_name,
                          "file": rel_path, "line": i, "domain": "backend"})

    # Functions (def)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # def with optional modifiers
        m = re.match(r'\s*(?:private\s+|protected\s+|override\s+|implicit\s+|lazy\s+)*(?:def)\s+(\w+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            ntype = "function"
            if fn_name == "main":
                ntype = "entry_point"
            elif fn_name.startswith("test") or fn_name.startswith("should"):
                ntype = "test"
            elif 'implicit' in line:
                ntype = "implicit_function"
            nodes.append({"id": node_id, "type": ntype,
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue
        # val / lazy val at object level (constants, important values)
        m = re.match(r'\s*(?:lazy\s+)?val\s+(\w+)\s*[:=]', line)
        if m:
            val_name = m.group(1)
            # Only track top-level or object-level vals, not local
            indent = len(line) - len(line.lstrip())
            if indent <= 4:
                node_id = f"{rel_path}:{i}:val_{val_name}"
                nodes.append({"id": node_id, "type": "value",
                              "name": val_name, "fn": val_name,
                              "file": rel_path, "line": i, "domain": "backend"})

    # ─── Function call edges ─────────────────────────────────────
    _SCALA_KEYWORDS = frozenset({
        'if', 'else', 'while', 'for', 'match', 'case', 'return', 'yield',
        'class', 'object', 'trait', 'def', 'val', 'var', 'import', 'package',
        'new', 'this', 'super', 'throw', 'try', 'catch', 'finally',
        'true', 'false', 'null', 'type', 'with', 'extends', 'forSome',
        'implicit', 'lazy', 'override', 'private', 'protected', 'sealed',
        'abstract', 'final', 'println', 'print', 'assert',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0
    brace_count = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("function", "entry_point", "test",
                                                                "implicit_function", "constructor"):
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
    call_pattern = re.compile(r'([\w]+)\.([\w]+)\s*[\(\[]')
    simple_call = re.compile(r'(?<!\.)([\w]+)\s*[\(\[]')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            obj = m.group(1)
            method = m.group(2)
            if obj in _SCALA_KEYWORDS or method in _SCALA_KEYWORDS:
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
        for m in simple_call.finditer(body):
            fn_name = m.group(1)
            if fn_name in _SCALA_KEYWORDS:
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

"""
Fallback Ruby Parser for CodeLens — regex-based extraction.
Extracts classes, modules, methods, constants, Rails patterns,
and method call relationships for edge resolution.
Supports: class, module, def, def self., include, extend, require,
          attr_accessor/reader/writer, before_action, has_many, etc.
"""

import re
from typing import Dict, List, Any


def parse_ruby_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Ruby source using regex — extracts classes, modules, methods, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Requires — module-level import edges
    for i, line in enumerate(lines, 1):
        m = re.match(r"\s*require\s+['\"]([^'\"]+)['\"]", line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})
            continue
        m = re.match(r"\s*require_relative\s+['\"]([^'\"]+)['\"]", line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})

    # Collect definitions
    fn_defs = {}   # method_name → node_id
    class_defs = {}  # class_name → node_id

    # Classes and Modules
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Module definition
        m = re.match(r'\s*module\s+([\w:]+)', line)
        if m:
            mod_name = m.group(1)
            node_id = f"{rel_path}:{i}:{mod_name}"
            nodes.append({"id": node_id, "type": "module",
                          "name": mod_name, "fn": mod_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            class_defs[mod_name] = node_id
            continue
        # Class definition (with optional inheritance)
        m = re.match(r'\s*class\s+([\w:]+)(?:\s*<\s*([\w:]+))?', line)
        if m:
            cls_name = m.group(1)
            parent = m.group(2) or ""
            node_id = f"{rel_path}:{i}:{cls_name}"
            nodes.append({"id": node_id, "type": "class",
                          "name": cls_name, "fn": cls_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "parent": parent})
            class_defs[cls_name] = node_id
            if parent:
                edges.append({"from": node_id, "to_fn": parent, "type": "inherits", "weight": 1})
            continue

    # Methods (instance and class)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Class method: def self.method_name
        m = re.match(r'\s*def\s+self\.([\w?!]+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:self.{fn_name}"
            nodes.append({"id": node_id, "type": "class_method",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            fn_defs[f"self.{fn_name}"] = node_id
            continue
        # Instance method: def method_name
        m = re.match(r'\s*def\s+([\w?!]+(?:\s*[\w?!]*)*)', line)
        if m:
            fn_name = m.group(1).split()[0]
            # Skip Ruby keywords
            if fn_name in ('if', 'unless', 'while', 'until', 'for', 'case', 'begin'):
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            ntype = "method"
            if fn_name == "initialize":
                ntype = "constructor"
            nodes.append({"id": node_id, "type": ntype,
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue
        # attr_accessor / attr_reader / attr_writer
        m = re.match(r'\s*attr_(accessor|reader|writer)\s+(.+)', line)
        if m:
            attr_type = m.group(1)
            attrs_str = m.group(2)
            # Parse :name, :name2 or "name", "name2" or name, name2
            attrs = re.findall(r'[:\"](\w+)[\":]', attrs_str)
            if not attrs:
                attrs = re.findall(r'(\w+)', attrs_str)
            for attr_name in attrs:
                node_id = f"{rel_path}:{i}:attr_{attr_name}"
                nodes.append({"id": node_id, "type": "attribute",
                              "name": attr_name, "fn": attr_name,
                              "file": rel_path, "line": i, "domain": "backend",
                              "attr_type": attr_type})

    # Rails-specific patterns
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # before_action / after_action
        m = re.match(r'\s*(before|after|around)_action\s+(.+)', line)
        if m:
            action_type = m.group(1)
            handlers = re.findall(r':([\w?!]+)', m.group(2))
            for handler in handlers:
                edges.append({"from": rel_path, "to_fn": handler, "type": "callback", "weight": 1})
            continue
        # has_many / belongs_to / has_one / has_and_belongs_to_many
        m = re.match(r'\s*(has_many|belongs_to|has_one|has_and_belongs_to_many)\s+:([\w]+)', line)
        if m:
            assoc_type = m.group(1)
            assoc_name = m.group(2)
            node_id = f"{rel_path}:{i}:{assoc_type}_{assoc_name}"
            nodes.append({"id": node_id, "type": "association",
                          "name": assoc_name, "fn": assoc_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "assoc_type": assoc_type})
            continue
        # scope
        m = re.match(r'\s*scope\s+:([\w]+)', line)
        if m:
            scope_name = m.group(1)
            node_id = f"{rel_path}:{i}:scope_{scope_name}"
            nodes.append({"id": node_id, "type": "scope",
                          "name": scope_name, "fn": scope_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # validates
        m = re.match(r'\s*validates\s+:([\w]+)', line)
        if m:
            val_name = m.group(1)
            node_id = f"{rel_path}:{i}:validates_{val_name}"
            nodes.append({"id": node_id, "type": "validation",
                          "name": val_name, "fn": val_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # include / extend
        m = re.match(r'\s*(include|extend)\s+([\w:]+)', line)
        if m:
            inc_type = m.group(1)
            inc_name = m.group(2)
            edges.append({"from": rel_path, "to_fn": inc_name, "type": inc_type, "weight": 1})

    # ─── Method call edges ─────────────────────────────────────
    _RUBY_KEYWORDS = frozenset({
        'if', 'unless', 'while', 'until', 'for', 'case', 'when', 'begin',
        'rescue', 'ensure', 'end', 'def', 'class', 'module', 'do', 'then',
        'else', 'elsif', 'return', 'yield', 'raise', 'next', 'break',
        'and', 'or', 'not', 'nil', 'true', 'false', 'self', 'super',
        'require', 'require_relative', 'include', 'extend', 'attr_accessor',
        'attr_reader', 'attr_writer', 'new', 'puts', 'print', 'p',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0
    depth = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("method", "class_method", "constructor"):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                depth = 0
                break

        if current_fn:
            stripped = line.strip()
            depth += stripped.count('do') + stripped.count('{') + stripped.count('begin')
            depth -= stripped.count('end') + stripped.count('}')

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each method body
    call_pattern = re.compile(r'([\w?!]+)\s*[\(\s]')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            call_name = m.group(1)
            if call_name in _RUBY_KEYWORDS:
                continue
            if call_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[call_name],
                    "to_fn": call_name,
                    "type": "call",
                    "weight": 1,
                })
            else:
                edges.append({
                    "from": fn_id,
                    "to_fn": call_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}

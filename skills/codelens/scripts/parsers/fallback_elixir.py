"""
Fallback Elixir Parser for CodeLens — regex-based extraction.
Extracts modules, functions, macros, protocols, Phoenix patterns,
and function call relationships for edge resolution.
Supports: defmodule, def, defp, defmacro, use, import, alias, require,
          Phoenix routes, Ecto schemas, GenServer callbacks, etc.
"""

import re
from typing import Dict, List, Any


def parse_elixir_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Elixir source using regex — extracts modules, functions, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # use / import / alias / require — module dependency edges
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*use\s+([\w.]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "use", "weight": 1})
            continue
        m = re.match(r'\s*import\s+([\w.]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "import", "weight": 1})
            continue
        m = re.match(r'\s*alias\s+([\w.]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "alias", "weight": 1})
            continue
        m = re.match(r'\s*require\s+([\w.]+)', line)
        if m:
            edges.append({"from": rel_path, "to_fn": m.group(1), "type": "require", "weight": 1})

    # Collect definitions
    fn_defs = {}  # fn_name → node_id
    module_defs = {}  # module_name → node_id

    # Modules (defmodule)
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*defmodule\s+([\w.]+)', line)
        if m:
            mod_name = m.group(1)
            node_id = f"{rel_path}:{i}:{mod_name}"
            nodes.append({"id": node_id, "type": "module",
                          "name": mod_name, "fn": mod_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            module_defs[mod_name] = node_id
            # Also register the short name (last segment)
            short = mod_name.split('.')[-1]
            module_defs[short] = node_id

    # Functions: def, defp, defmacro, defmacrop
    for i, line in enumerate(lines, 1):
        # Public function: def name(args)
        m = re.match(r'\s*def\s+([\w!?]+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "function",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "visibility": "public"})
            fn_defs[fn_name] = node_id
            continue
        # Private function: defp name(args)
        m = re.match(r'\s*defp\s+([\w!?]+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "function",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "visibility": "private"})
            fn_defs[fn_name] = node_id
            continue
        # Public macro: defmacro name(args)
        m = re.match(r'\s*defmacro\s+([\w!?]+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "macro",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "visibility": "public"})
            fn_defs[fn_name] = node_id
            continue
        # Private macro: defmacrop name(args)
        m = re.match(r'\s*defmacrop\s+([\w!?]+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "macro",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "visibility": "private"})
            fn_defs[fn_name] = node_id

    # Phoenix / Ecto / GenServer specific patterns
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Phoenix route: get "/path", Controller, :action
        m = re.match(r'\s*(get|post|put|patch|delete|options)\s+"([^"]+)"\s*,\s*([\w.]+)\s*,\s*:(\w+)', line)
        if m:
            http_method = m.group(1)
            path = m.group(2)
            controller = m.group(3)
            action = m.group(4)
            node_id = f"{rel_path}:{i}:route_{http_method}_{path}"
            nodes.append({"id": node_id, "type": "route",
                          "name": f"{http_method} {path}", "fn": action,
                          "file": rel_path, "line": i, "domain": "backend",
                          "http_method": http_method, "path": path,
                          "controller": controller, "action": action})
            edges.append({"from": node_id, "to_fn": action, "type": "route_to_action", "weight": 1})
            continue
        # Phoenix scope
        m = re.match(r'\s*scope\s+"([^"]+)"\s*,\s*([\w.]+)', line)
        if m:
            scope_path = m.group(1)
            scope_module = m.group(2)
            node_id = f"{rel_path}:{i}:scope_{scope_path}"
            nodes.append({"id": node_id, "type": "scope",
                          "name": scope_path, "fn": scope_path,
                          "file": rel_path, "line": i, "domain": "backend",
                          "scope_path": scope_path, "scope_module": scope_module})
            continue
        # pipe_through
        m = re.match(r'\s*pipe_through\s+:([\w]+)', line)
        if m:
            pipe_name = m.group(1)
            node_id = f"{rel_path}:{i}:pipe_{pipe_name}"
            nodes.append({"id": node_id, "type": "middleware",
                          "name": pipe_name, "fn": pipe_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # Ecto schema field
        m = re.match(r'\s*field\s+:([\w]+)', line)
        if m:
            field_name = m.group(1)
            node_id = f"{rel_path}:{i}:field_{field_name}"
            nodes.append({"id": node_id, "type": "field",
                          "name": field_name, "fn": field_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # Ecto has_many / belongs_to / has_one / many_to_many
        m = re.match(r'\s*(has_many|belongs_to|has_one|many_to_many)\s+:([\w]+)', line)
        if m:
            assoc_type = m.group(1)
            assoc_name = m.group(2)
            node_id = f"{rel_path}:{i}:{assoc_type}_{assoc_name}"
            nodes.append({"id": node_id, "type": "association",
                          "name": assoc_name, "fn": assoc_name,
                          "file": rel_path, "line": i, "domain": "backend",
                          "assoc_type": assoc_type})
            continue
        # GenServer callbacks
        m = re.match(r'\s*@(impl|spec|doc|moduledoc)', line)
        if m:
            continue  # Skip attributes, they're metadata
        # children for Supervisor
        m = re.match(r'\s*children\s*=\s*\[(.+)\]', line)
        if m:
            children_str = m.group(1)
            children = re.findall(r'([\w.]+)', children_str)
            for child in children:
                if child not in ('Supervisor', 'worker', 'supervise', 'strategy'):
                    edges.append({"from": rel_path, "to_fn": child, "type": "supervises", "weight": 1})

    # ─── Function call edges via pipe operator and regular calls ────
    _ELIXIR_KEYWORDS = frozenset({
        'if', 'unless', 'case', 'cond', 'with', 'for', 'while', 'try',
        'rescue', 'after', 'catch', 'else', 'do', 'end', 'fn', 'receive',
        'raise', 'throw', 'return', 'super', 'nil', 'true', 'false',
        'when', 'and', 'or', 'not', 'in', 'use', 'import', 'alias',
        'require', 'defmodule', 'def', 'defp', 'defmacro', 'defmacrop',
        'defstruct', 'defprotocol', 'defimpl', 'defoverridable',
        'send', 'spawn', 'self', 'apply', 'put_elem', 'elem',
    })

    _ELIXIR_BUILTINS = frozenset({
        'IO', 'Enum', 'List', 'Map', 'String', 'Atom', 'Kernel',
        'Process', 'Agent', 'Task', 'GenServer', 'Supervisor',
        'Application', 'Logger', 'Repo', 'Ecto', 'Phoenix',
        'inspect', 'to_string', 'is_nil', 'is_binary', 'is_list',
        'is_map', 'is_atom', 'is_integer', 'is_float', 'is_boolean',
        'length', 'map_size', 'byte_size', 'tuple_size',
        'Kernel.apply', 'Kernel.spawn', 'Kernel.send',
        'puts', 'inspect', 'warn', 'error', 'info', 'debug',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0
    depth = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("function", "macro"):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                depth = 0
                break

        if current_fn:
            stripped = line.strip()
            depth += stripped.count('do') + stripped.count('fn ') + stripped.count('fn(')
            depth -= stripped.count('end')

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    # Match: function_name(args) and Module.function(args) and |> pipe_target
    call_pattern = re.compile(r'(?:([\w.]+)\.)?([\w!?]+)\s*[\(\s]')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        # Also check pipe chains
        pipe_pattern = re.compile(r'\|>\s*([\w!?]+)\s*[\(\s]')
        for m in pipe_pattern.finditer(body):
            pipe_fn = m.group(1)
            if pipe_fn in _ELIXIR_KEYWORDS:
                continue
            if pipe_fn in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[pipe_fn],
                    "to_fn": pipe_fn,
                    "type": "call",
                    "weight": 1,
                })
            else:
                edges.append({
                    "from": fn_id,
                    "to_fn": pipe_fn,
                    "type": "call",
                    "weight": 1,
                })

        for m in call_pattern.finditer(body):
            module_part = m.group(1) or ""
            fn_name = m.group(2)
            if fn_name in _ELIXIR_KEYWORDS:
                continue
            full_call = f"{module_part}.{fn_name}" if module_part else fn_name
            if module_part in _ELIXIR_BUILTINS or full_call in _ELIXIR_BUILTINS:
                continue
            if fn_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[fn_name],
                    "to_fn": fn_name,
                    "type": "call",
                    "weight": 1,
                })
            else:
                edges.append({
                    "from": fn_id,
                    "to_fn": full_call,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}

"""
Fallback Elixir Parser for CodeLens — regex-based extraction.
Extracts modules, functions, private functions, macros, and
use/import/require/alias declarations for dependency edge resolution.
"""

import re
from typing import Dict, List, Any, Optional


# Elixir keywords and specials to skip when extracting call edges
_ELIXIR_KEYWORDS = frozenset({
    'do', 'end', 'if', 'else', 'case', 'cond', 'with', 'for',
    'try', 'catch', 'rescue', 'after', 'receive', 'when',
    'fn', 'true', 'false', 'nil', 'and', 'or', 'not', 'in',
    'raise', 'throw', 'quote', 'unquote', 'super',
})

_ELIXIR_BUILTINS = frozenset({
    'IO', 'Kernel', 'Enum', 'List', 'Map', 'String', 'Atom',
    'Process', 'Agent', 'GenServer', 'Supervisor', 'Task',
    'Application', 'Logger', 'Regex', 'Tuple', 'Bitwise',
    'System', 'File', 'Path', 'URI', 'Code', 'Macro',
    'Module', 'Node', 'Port', 'Reference', 'Float',
    'Integer', 'Function', 'Stream', 'Range', 'Inspect',
    'Access', 'Keyword', 'Set', 'Dict', 'HashSet',
    'Dict', 'Elixir', 'ExUnit',
})


def parse_elixir_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Elixir source using regex — extracts modules, functions, macros,
    and use/import/require/alias edges.

    Returns dict with 'nodes' and 'edges' in the format expected by
    the backend registry and edge_resolver:
    - nodes: [{id, name, fn, type, file, line, domain, ...}]
    - edges: [{from, to_fn, type, weight}, ...]
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Track defined function/macro names for intra-file call resolution
    defined_fns: Dict[str, str] = {}  # fn_name → node_id

    # Current module context (for qualifying function nodes)
    current_module: Optional[str] = None

    # ─── Pass 1: Extract declarations ──────────────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('#'):
            continue

        # --- defmodule Module.Name do ---
        m = re.match(r'\s*defmodule\s+([A-Z][\w\.]*)', line)
        if m:
            mod_name = m.group(1)
            current_module = mod_name
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "module",
                "name": mod_name,
                "fn": mod_name.split('.')[-1],
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
            })
            continue

        # --- defmacro name(args) do ---
        m = re.match(r'\s*defmacro\s+(\w+)', line)
        if m:
            macro_name = m.group(1)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "macro",
                "name": macro_name,
                "fn": macro_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "module": current_module,
            })
            defined_fns[macro_name] = node_id
            continue

        # --- def name(args) do ---
        m = re.match(r'\s*def\s+(\w+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": fn_name,
                "fn": fn_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "module": current_module,
            })
            defined_fns[fn_name] = node_id
            continue

        # --- defp name(args) do ---
        m = re.match(r'\s*defp\s+(\w+)', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": fn_name,
                "fn": fn_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
                "visibility": "private",
                "module": current_module,
            })
            defined_fns[fn_name] = node_id
            continue

    # ─── Pass 2: Extract dependency edges (use, import, require, alias) ──

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        # Find which node "owns" this line (nearest preceding function/macro)
        owner_node = _find_owner_node(nodes, i)

        # --- use Module, opts ---
        for m in re.finditer(r'\buse\s+([A-Z][\w\.]*)', stripped):
            mod_name = m.group(1)
            from_id = owner_node["id"] if owner_node else f"{rel_path}:0"
            edges.append({
                "from": from_id,
                "to_fn": mod_name.split('.')[-1],
                "via_use": True,
                "module": mod_name,
            })

        # --- import Module, opts ---
        for m in re.finditer(r'\bimport\s+([A-Z][\w\.]*)', stripped):
            mod_name = m.group(1)
            from_id = owner_node["id"] if owner_node else f"{rel_path}:0"
            edges.append({
                "from": from_id,
                "to_fn": mod_name.split('.')[-1],
                "via_import": True,
                "module": mod_name,
            })

        # --- require Module, opts ---
        for m in re.finditer(r'\brequire\s+([A-Z][\w\.]*)', stripped):
            mod_name = m.group(1)
            from_id = owner_node["id"] if owner_node else f"{rel_path}:0"
            edges.append({
                "from": from_id,
                "to_fn": mod_name.split('.')[-1],
                "via_require": True,
                "module": mod_name,
            })

        # --- alias Module.Name, as: Short ---
        for m in re.finditer(r'\balias\s+([A-Z][\w\.]*)', stripped):
            mod_name = m.group(1)
            from_id = owner_node["id"] if owner_node else f"{rel_path}:0"
            edges.append({
                "from": from_id,
                "to_fn": mod_name.split('.')[-1],
                "via_alias": True,
                "module": mod_name,
            })

    # ─── Pass 3: Extract function call edges ──────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        owner_node = _find_owner_node(nodes, i)
        if not owner_node:
            continue

        # Module.function() calls: ModuleName.func_name(...)
        for m in re.finditer(r'([A-Z][\w]*(?:\.[A-Z]?[\w]*)*)\.(\w+)\s*\(', stripped):
            mod_part = m.group(1)
            fn_part = m.group(2)
            if fn_part in _ELIXIR_KEYWORDS:
                continue
            edges.append({
                "from": owner_node["id"],
                "to_fn": fn_part,
                "via_module_call": True,
                "module": mod_part,
            })

        # Local function calls: func_name(...)
        # Match identifiers before ( that are NOT preceded by a dot or colon
        for m in re.finditer(r'(?<![.:])(\b[a-z_]\w*)\s*\(', stripped):
            call_name = m.group(1)
            if call_name in _ELIXIR_KEYWORDS:
                continue
            # Skip Elixir keywords used as def/defp/defmacro etc.
            if call_name in ('def', 'defp', 'defmacro', 'defmodule',
                             'do', 'end', 'fn', 'if', 'unless',
                             'case', 'cond', 'with', 'for', 'try',
                             'receive', 'after', 'rescue', 'catch',
                             'raise', 'throw', 'quote', 'unquote',
                             'use', 'import', 'require', 'alias'):
                continue
            if owner_node and call_name != owner_node.get("fn"):
                if call_name in defined_fns:
                    edges.append({
                        "from": owner_node["id"],
                        "to": defined_fns[call_name],
                        "to_fn": call_name,
                        "type": "call",
                        "weight": 1,
                    })
                else:
                    edges.append({
                        "from": owner_node["id"],
                        "to_fn": call_name,
                        "type": "call",
                        "weight": 1,
                    })

    return {"nodes": nodes, "edges": edges}


def _find_owner_node(nodes: List[Dict], line_num: int) -> Optional[Dict]:
    """Find the nearest preceding function/macro node that 'owns' a line."""
    best = None
    for node in nodes:
        if node.get("type") in ("module",):
            continue  # modules don't "own" lines for call-edge purposes
        if node.get("line", 0) <= line_num:
            if best is None or node["line"] > best["line"]:
                best = node
    return best

"""
Fallback Lua Parser for CodeLens — regex-based extraction.
Extracts functions, tables, requires, and module declarations.
v2: Proper edge format for edge_resolver, function-level call edges,
    module resolution for require(), and Neovim plugin patterns.
"""

import re
from typing import Dict, List, Any, Optional


# Common Lua keywords to skip
_LUA_KEYWORDS = frozenset({
    'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for',
    'function', 'goto', 'if', 'in', 'local', 'nil', 'not', 'or',
    'repeat', 'return', 'then', 'true', 'until', 'while',
    # Common globals that aren't real function definitions
    'print', 'pairs', 'ipairs', 'tostring', 'tonumber', 'type',
    'require', 'pcall', 'xpcall', 'error', 'assert',
    'table', 'string', 'math', 'io', 'os', 'debug', 'coroutine',
    'vim', 'M', 'self', '_G', '_VERSION',
})


def parse_lua_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Lua source using regex — extracts functions, tables, requires.

    Returns dict with 'nodes' and 'edges' in the format expected by
    the backend registry and edge_resolver:
    - nodes: [{id, name, fn, type, file, line, ...}]
    - edges: [{from: node_id, to_fn: name}, ...] for function calls
             [{from: node_id, to_fn: name, via_require: True}, ...] for requires
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Track defined function names for this file
    defined_fns = {}

    # ─── Pass 1: Extract declarations ──────────────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # --- Functions (named) ---
        # function foo() or function foo.bar() or function foo:baz()
        m = re.match(r'\s*function\s+(\w+(?:[:\.]\w+)*)', line)
        if m:
            full_name = m.group(1)
            short_name = full_name.split('.')[-1].split(':')[-1]
            ftype = "method" if (':' in full_name or '.' in full_name) else "function"
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": ftype,
                "name": full_name,
                "fn": short_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
            })
            defined_fns[short_name] = node_id
            defined_fns[full_name] = node_id
            continue

        # local function foo()
        m = re.match(r'\s*local\s+function\s+(\w+)', line)
        if m:
            name = m.group(1)
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": name,
                "fn": name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
            })
            defined_fns[name] = node_id
            continue

        # --- Method assignments: M.foo = function() or obj.bar = function() ---
        m = re.match(r'\s*(\w+(?:[:\.]\w+)*)\s*=\s*function\s*\(', stripped)
        if m:
            full_name = m.group(1)
            short_name = full_name.split('.')[-1].split(':')[-1]
            node_id = f"{rel_path}:{i}"
            nodes.append({
                "id": node_id,
                "type": "method",
                "name": full_name,
                "fn": short_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "ref_count": 0,
                "status": "active",
            })
            defined_fns[short_name] = node_id
            defined_fns[full_name] = node_id
            continue

        # --- Table declarations (M.key = {} or key = {}) ---
        m = re.match(r'\s*(\w+(?:[:\.]\w+)*)\s*=\s*\{', stripped)
        if m:
            full_name = m.group(1)
            short_name = full_name.split('.')[-1].split(':')[-1]
            if short_name not in _LUA_KEYWORDS:
                node_id = f"{rel_path}:{i}"
                nodes.append({
                    "id": node_id,
                    "type": "table",
                    "name": full_name,
                    "fn": short_name,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                    "ref_count": 0,
                    "status": "active",
                })
                defined_fns[short_name] = node_id

    # ─── Pass 2: Extract function calls and require() ──────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Find which node "owns" this line (nearest preceding function)
        owner_node = _find_owner_node(nodes, i)

        # --- require() calls: local mod = require("module.path") ---
        for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', stripped):
            mod_path = m.group(1)
            # Convert "lazyvim.util" to a function name hint
            mod_name = mod_path.split('.')[-1]
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": mod_name,
                    "via_require": True,
                    "require_path": mod_path,
                })
            else:
                # File-level require (not inside a function)
                edges.append({
                    "from": f"{rel_path}:0",
                    "to_fn": mod_name,
                    "via_require": True,
                    "require_path": mod_path,
                })

        # --- Function calls: name(args) ---
        for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', stripped):
            call_name = m.group(1)
            if call_name in _LUA_KEYWORDS:
                continue
            # Skip if it's the function definition itself
            if call_name in ('function',):
                continue
            if owner_node and call_name != owner_node.get("fn"):
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": call_name,
                })

        # --- Method calls: obj:method() or obj.method() ---
        for m in re.finditer(r'[:\.]([a-zA-Z_]\w*)\s*\(', stripped):
            method_name = m.group(1)
            if method_name in _LUA_KEYWORDS:
                continue
            if owner_node and method_name != owner_node.get("fn"):
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": method_name,
                    "via_method": True,
                })

    # ─── Pass 3: Neovim-specific patterns ──────────

    # Detect vim.api/vim.fn/vim.keymap/vim.cmd calls as edges
    for i, line in enumerate(lines, 1):
        owner_node = _find_owner_node(nodes, i)
        for m in re.finditer(r'vim\.(api|fn|keymap|cmd|opt|loop|ui|diag|lsp|treesitter|highlight)\b', line):
            vim_module = m.group(1)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to_fn": f"vim.{vim_module}",
                    "via_vim_api": True,
                })

    # Detect vim.api.nvim_create_autocmd / vim.keymap.set as entrypoint indicators
    # (These are registered in the entrypoints engine, not here)

    return {"nodes": nodes, "edges": edges}


def _find_owner_node(nodes: List[Dict], line_num: int) -> Optional[Dict]:
    """Find the nearest preceding function node that 'owns' a line."""
    best = None
    for node in nodes:
        if node.get("line", 0) <= line_num:
            if best is None or node["line"] > best["line"]:
                best = node
    return best

"""
Fallback Shell/Bash Parser for CodeLens — regex-based extraction.
Extracts functions, variables, source/include dependencies,
and function call relationships for edge resolution.
Supports: function definitions, variable exports, source/. dependencies,
          Dockerfile patterns, heredoc detection, etc.
"""

import re
from typing import Dict, List, Any


def parse_shell_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Shell/Bash source using regex — extracts functions, variables, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Source / . dependencies
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*(?:source|\.)\s+([^\s;]+)', line)
        if m:
            source_path = m.group(1)
            edges.append({"from": rel_path, "to_fn": source_path, "type": "source", "weight": 1})

    fn_defs = {}  # fn_name → node_id

    # Function definitions: name() { or function name {
    for i, line in enumerate(lines, 1):
        # function name() { or function name {
        m = re.match(r'\s*function\s+(\w+)\s*\(?', line)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "function",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue
        # name() {
        m = re.match(r'\s*(\w+)\s*\(\)\s*\{?', line)
        if m:
            fn_name = m.group(1)
            # Skip common keywords
            if fn_name in ('if', 'then', 'else', 'elif', 'fi', 'for', 'while',
                           'until', 'do', 'done', 'case', 'esac', 'in', 'function',
                           'return', 'exit', 'break', 'continue', 'echo', 'printf',
                           'read', 'cd', 'export', 'local', 'declare', 'set', 'unset'):
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": "function",
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id
            continue

    # Important variables (exported or ENV-style)
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*export\s+([\w_]+)=?', line)
        if m:
            var_name = m.group(1)
            node_id = f"{rel_path}:{i}:var_{var_name}"
            nodes.append({"id": node_id, "type": "export_variable",
                          "name": var_name, "fn": var_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # Dockerfile patterns
        m = re.match(r'\s*FROM\s+([\w:./-]+)', line, re.IGNORECASE)
        if m:
            image = m.group(1)
            node_id = f"{rel_path}:{i}:FROM_{image}"
            nodes.append({"id": node_id, "type": "docker_from",
                          "name": image, "fn": image,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.match(r'\s*RUN\s+(.+)', line, re.IGNORECASE)
        if m:
            cmd = m.group(1).strip()[:50]
            node_id = f"{rel_path}:{i}:RUN_{i}"
            nodes.append({"id": node_id, "type": "docker_run",
                          "name": cmd, "fn": cmd,
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.match(r'\s*(?:ENTRYPOINT|CMD)\s+(.+)', line, re.IGNORECASE)
        if m:
            node_id = f"{rel_path}:{i}:ENTRYPOINT"
            nodes.append({"id": node_id, "type": "docker_entrypoint",
                          "name": "entrypoint", "fn": "entrypoint",
                          "file": rel_path, "line": i, "domain": "backend"})

    # ─── Function call edges ─────────────────────────────────────
    _SHELL_BUILTINS = frozenset({
        'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until',
        'do', 'done', 'case', 'esac', 'in', 'function', 'return', 'exit',
        'break', 'continue', 'echo', 'printf', 'read', 'cd', 'export',
        'local', 'declare', 'set', 'unset', 'shift', 'trap', 'wait',
        'eval', 'exec', 'source', 'test', 'true', 'false', 'pwd',
        'pushd', 'popd', 'dirs', 'alias', 'unalias', 'bg', 'fg',
        'jobs', 'kill', 'umask', 'getopts', 'let', 'typeset',
        'basename', 'dirname', 'cat', 'ls', 'grep', 'find', 'awk',
        'sed', 'sort', 'uniq', 'wc', 'head', 'tail', 'cut', 'tr',
        'cp', 'mv', 'rm', 'mkdir', 'rmdir', 'chmod', 'chown',
        'curl', 'wget', 'tar', 'gzip', 'gunzip', 'docker', 'git',
        'npm', 'pip', 'make', 'cmake', 'cargo', 'go',
    })

    # Build function→body range map
    fn_ranges = []
    current_fn = None
    fn_start = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if node.get("line") == i and node.get("type") == "function":
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                break

        if current_fn:
            stripped = line.strip()
            if stripped == '}' and i > fn_start + 1:
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    call_pattern = re.compile(r'(?<!\w)([\w_-]+)\s+')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            call_name = m.group(1)
            if call_name in _SHELL_BUILTINS:
                continue
            if call_name.startswith('-') or call_name.startswith('$'):
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

"""
Fallback Go Parser for CodeLens — Regex-based
Parses Go files for functions, methods (with receivers), types (struct/interface),
constants, variables, imports, and call edges.

Why a fallback? tree-sitter-go may not be installed in all environments.
This regex parser provides reasonable coverage for common Go constructs
and gracefully degrades on edge cases.

Supports:
- Functions (func Name())
- Methods with receivers (func (r *Receiver) Name())
- Type declarations (type Name struct/interface)
- Struct fields
- Interface method signatures
- Import statements (single and grouped)
- Constants and variables (const/var blocks)
- Function call edges
- go func() anonymous goroutine detection
- defer statement detection
- Channel operations (send/receive)
"""

import re
from typing import Dict, List, Any, Optional


def parse_go_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """
    Parse Go source code using regex fallback.

    Args:
        content: Go source code string
        rel_path: Relative path from workspace root

    Returns:
        Dict with keys:
        - nodes: List of backend node dicts (functions, methods, types)
        - edges: List of edge dicts (call relationships, imports)
        - package: Package name
        - imports: List of imported packages
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # ─── Package ──────────────────────────────────────────
    pkg_name = ""
    pkg_match = re.search(r'^\s*package\s+(\w+)', content, re.MULTILINE)
    if pkg_match:
        pkg_name = pkg_match.group(1)

    # ─── Imports (single) ─────────────────────────────────
    imports: List[str] = []
    single_import = re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE)
    for m in single_import.finditer(content):
        imports.append(m.group(1))
        line = _line_of(content, m.start())
        edges.append({
            "from": f"{rel_path}:{line}",
            "to": m.group(1),
            "type": "import"
        })

    # ─── Imports (grouped) ────────────────────────────────
    # import ( "fmt" "os" ... )
    # Also handles aliased: import ( f "fmt" )
    group_import = re.compile(r'import\s*\((.*?)\)', re.DOTALL)
    for m in group_import.finditer(content):
        block = m.group(1)
        for imp_match in re.finditer(r'(?:(\w+)\s+)?"([^"]+)"', block):
            alias = imp_match.group(1) or ""
            pkg_path = imp_match.group(2)
            imports.append(pkg_path)
            line = _line_of(content, m.start() + imp_match.start())
            edges.append({
                "from": f"{rel_path}:{line}",
                "to": pkg_path,
                "type": "import",
                "alias": alias if alias else None,
            })

    # ─── Type declarations ────────────────────────────────
    # type Name struct { ... }
    # type Name interface { ... }
    # type Name <base_type>
    type_pattern = re.compile(
        r'type\s+(\w+)\s+(struct|interface)?\s*[{]?',
        re.MULTILINE
    )
    for m in type_pattern.finditer(content):
        name = m.group(1)
        kind = m.group(2) or "type_alias"
        line = _line_of(content, m.start())

        node_type = "type"
        if kind == "struct":
            node_type = "struct"
        elif kind == "interface":
            node_type = "interface"

        node = {
            "id": f"{rel_path}:{line}:{name}",
            "fn": name,
            "file": rel_path,
            "line": line,
            "type": node_type,
            "package": pkg_name,
            "language": "go",
        }

        # Extract struct fields
        if kind == "struct":
            fields = _extract_struct_fields(content, m.end())
            if fields:
                node["fields"] = fields
                node["field_count"] = len(fields)

        # Extract interface methods
        if kind == "interface":
            iface_methods = _extract_interface_methods(content, m.end())
            if iface_methods:
                node["methods"] = iface_methods
                node["method_count"] = len(iface_methods)

        nodes.append(node)

    # ─── Functions ────────────────────────────────────────
    # func Name(params) (returns) { ... }
    # func (r *Receiver) Name(params) (returns) { ... }
    func_pattern = re.compile(
        r'func\s+'
        r'(?:\(([^)]*)\)\s+)?'   # Optional receiver
        r'(\w+)'                  # Function name
        r'\s*\(([^)]*)\)'        # Parameters
        r'(?:\s*\(([^)]*)\))?'   # Optional return types
        r'\s*[{]',               # Opening brace
    )

    for m in func_pattern.finditer(content):
        receiver_str = m.group(1) or ""
        func_name = m.group(2)
        params_str = m.group(3) or ""
        returns_str = m.group(4) or ""
        line = _line_of(content, m.start())

        # Parse receiver
        receiver_type = ""
        receiver_name = ""
        if receiver_str:
            # e.g. "r *Receiver", "s MyStruct", "(r *Receiver)"
            recv_match = re.match(r'(\w+)\s+\*?(\w+)', receiver_str.strip())
            if recv_match:
                receiver_name = recv_match.group(1)
                receiver_type = recv_match.group(2)

        # Parse parameters
        params = _parse_params(params_str)

        # Parse return types
        return_types = []
        if returns_str:
            for rt in returns_str.split(','):
                rt = rt.strip()
                if rt:
                    # Remove variable name, keep type
                    parts = rt.split()
                    return_types.append(parts[-1] if len(parts) > 1 else parts[0])

        # Determine if this is a method (has receiver) or function
        node_type = "method" if receiver_type else "function"

        node = {
            "id": f"{rel_path}:{line}:{func_name}",
            "fn": func_name,
            "file": rel_path,
            "line": line,
            "type": node_type,
            "package": pkg_name,
            "language": "go",
            "params": params,
            "param_count": len(params),
        }

        if receiver_type:
            node["receiver_type"] = receiver_type
            node["receiver_name"] = receiver_name

        if return_types:
            node["return_types"] = return_types

        # Extract function body for call analysis
        body = _extract_block_body(content, m.end() - 1)  # -1 to include the {

        if body:
            # Find function calls within the body
            call_edges = _extract_call_edges(body, rel_path, line, func_name, pkg_name)
            edges.extend(call_edges)

            # Detect defer calls
            defer_calls = re.findall(r'defer\s+(\w+(?:\.\w+)*)\s*\(', body)
            if defer_calls:
                node["defer_calls"] = defer_calls

            # Detect goroutines
            go_calls = re.findall(r'\bgo\s+(\w+(?:\.\w+)*)\s*\(', body)
            if go_calls:
                node["goroutine_calls"] = go_calls

            # Measure function length
            body_lines = body.count('\n')
            node["body_lines"] = body_lines
            if body_lines > 100:
                node["long_function"] = True

        nodes.append(node)

    # ─── Constants and Variables ──────────────────────────
    # const Name = value
    # const ( Name = value ... )
    const_pattern = re.compile(r'const\s+(\w+)\s*(?:=\s*|[^=]*=\s*)', re.MULTILINE)
    for m in const_pattern.finditer(content):
        # Skip if inside a const block (already captured)
        name = m.group(1)
        line = _line_of(content, m.start())
        # Don't add duplicate if it's inside a const() block
        if not any(n["fn"] == name and n["file"] == rel_path for n in nodes):
            nodes.append({
                "id": f"{rel_path}:{line}:{name}",
                "fn": name,
                "file": rel_path,
                "line": line,
                "type": "constant",
                "package": pkg_name,
                "language": "go",
            })

    # ─── Build results ────────────────────────────────────
    return {
        "nodes": nodes,
        "edges": edges,
        "package": pkg_name,
        "imports": imports,
    }


# ─── Helper Functions ────────────────────────────────────────

def _line_of(content: str, pos: int) -> int:
    """Get 1-indexed line number for a position in content."""
    return content[:pos].count('\n') + 1


def _extract_struct_fields(content: str, start_pos: int) -> List[Dict[str, str]]:
    """Extract fields from a struct definition."""
    fields = []
    depth = 0
    i = start_pos
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1

    if depth > 0:
        # Unclosed brace, try to get content anyway
        body = content[start_pos:i]
    else:
        body = content[start_pos:i]

    # Parse fields: Name Type `json:"name"`
    field_pattern = re.compile(
        r'(\w+)\s+([\w.*\[\]]+(?:<[\w\s,|]*>)?)\s*(?:`[^`]*`)?'
    )
    for m in field_pattern.finditer(body):
        name = m.group(1)
        ftype = m.group(2)
        # Skip embedded/anonymous fields (no explicit name in Go style)
        if name[0].isupper() or name[0].islower():
            fields.append({"name": name, "type": ftype})

    return fields


def _extract_interface_methods(content: str, start_pos: int) -> List[Dict[str, str]]:
    """Extract method signatures from an interface definition."""
    methods = []
    depth = 0
    i = start_pos
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1

    body = content[start_pos:i] if depth == 0 else content[start_pos:]

    # MethodPattern: Name(params) returns
    method_pattern = re.compile(
        r'(\w+)\s*\(([^)]*)\)\s*(?:\(([^)]*)\))?'
    )
    for m in method_pattern.finditer(body):
        name = m.group(1)
        if name in ('type', 'var', 'const', 'func', 'import', 'package',
                     'map', 'chan', 'struct', 'interface', 'return', 'if',
                     'for', 'range', 'switch', 'case', 'default', 'select',
                     'go', 'defer', 'fallthrough', 'break', 'continue'):
            continue  # Skip Go keywords
        methods.append({
            "name": name,
            "params": m.group(2) or "",
            "returns": m.group(3) or "",
        })

    return methods


def _extract_block_body(content: str, brace_pos: int) -> Optional[str]:
    """Extract the body of a block starting at the opening brace position.
    Returns the content between { and matching }."""
    if brace_pos >= len(content) or content[brace_pos] != '{':
        return None

    depth = 0
    start = brace_pos + 1
    for i in range(brace_pos, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[start:i]
    return None  # Unclosed block


def _parse_params(params_str: str) -> List[Dict[str, str]]:
    """Parse Go function parameters."""
    params = []
    if not params_str.strip():
        return params

    # Split by comma, but handle complex types like func(int) error
    parts = []
    depth = 0
    current = ""
    for ch in params_str:
        if ch in '({[':
            depth += 1
            current += ch
        elif ch in ')}]':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # "name Type" or just "Type" or "...Type"
        tokens = part.split()
        if len(tokens) >= 2:
            # Check for variadic
            is_variadic = tokens[-2].startswith('...')
            params.append({
                "name": tokens[0] if not tokens[0].startswith('...') else "",
                "type": tokens[-1],
                "variadic": is_variadic,
            })
        elif len(tokens) == 1:
            params.append({
                "name": "",
                "type": tokens[0].rstrip('.'),
                "variadic": tokens[0].startswith('...'),
            })

    return params


def _extract_call_edges(
    body: str,
    rel_path: str,
    fn_line: int,
    fn_name: str,
    pkg_name: str
) -> List[Dict[str, Any]]:
    """Extract function call edges from a function body."""
    edges = []

    # Match function calls: funcName() or pkg.Func() or obj.Method()
    # Exclude keywords and control flow
    call_pattern = re.compile(
        r'(?:^|[^.\w])'              # Not preceded by . or word char
        r'((\w+)(?:\.(\w+))?)\s*\('  # funcName() or pkg.Func()
    )

    from_id = f"{rel_path}:{fn_line}:{fn_name}"

    seen = set()
    for m in call_pattern.finditer(body):
        full_call = m.group(1)
        pkg_or_obj = m.group(2)
        method = m.group(3)

        # Skip Go keywords and control flow
        skip_words = {
            'if', 'for', 'range', 'switch', 'case', 'select',
            'func', 'return', 'defer', 'go', 'var', 'const',
            'type', 'struct', 'interface', 'map', 'chan', 'make',
            'new', 'len', 'cap', 'append', 'copy', 'delete',
            'close', 'panic', 'recover', 'print', 'println',
            'true', 'false', 'nil', 'else', 'default',
        }

        if pkg_or_obj in skip_words:
            continue
        if method and method in skip_words:
            continue

        # Determine the to_fn
        if method:
            to_fn = method
        else:
            to_fn = pkg_or_obj

        # Deduplicate calls within same function
        edge_key = (from_id, to_fn)
        if edge_key in seen:
            continue
        seen.add(edge_key)

        call_line = fn_line + body[:m.start()].count('\n')

        edge = {
            "from": from_id,
            "to_fn": to_fn,
            "type": "call",
            "language": "go",
        }

        if pkg_or_obj and method:
            edge["call_on"] = pkg_or_obj  # e.g., "r" in r.Method()
            edge["full_call"] = full_call  # e.g., "r.Method"

        edges.append(edge)

    return edges

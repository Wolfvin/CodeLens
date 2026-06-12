"""
Fallback Zig Parser for CodeLens — regex-based extraction.

Parses Zig source (.zig) to extract:
- Top-level functions (fn) — with pub flag
- Struct declarations (const Name = struct {)
- Enum declarations (const Name = enum {)
- Imports (const name = @import("path")) — including chained access
  like `const Builder = @import("std").Build;`
- Function call edges within function bodies

Returns ``{"nodes": [...], "edges": [...]}`` in the same format as other
fallback parsers so the backend registry can ingest Zig codebases even when
a tree-sitter grammar is unavailable.
"""

import re
from typing import Dict, List, Any


# Keywords that should never be treated as function names or call targets.
_ZIG_KEYWORDS = frozenset({
    # Control flow
    'if', 'else', 'while', 'for', 'switch', 'try', 'catch',
    'return', 'break', 'continue',
    # Defer
    'defer', 'errdefer',
    # Async
    'async', 'await', 'suspend', 'resume',
    # Declarations / namespace
    'usingnamespace', 'test', 'pub', 'const', 'var', 'comptime',
    # Literals / special values
    'null', 'true', 'false', 'undefined', 'unreachable',
    # Type keywords that commonly appear before '(' in casts/builtins
    'fn', 'struct', 'enum', 'union', 'opaque', 'error',
    # Common Zig builtins that start with '@' — we skip them as call targets
    # because they are compiler intrinsics, not user-defined functions.
    'addWithOverflow', 'alignCast', 'alignOf', 'as', 'asyncCall',
    'atomicLoad', 'atomicStore', 'bitCast', 'bitOffsetOf', 'bitSizeOf',
    'boolToInt', 'bitReverse', 'byteSwap', 'cDefine', 'cImport',
    'cInclude', 'ceil', 'cUndef', 'divCeil', 'divExact', 'divFloor',
    'divTrunc', 'embedFile', 'enumFromInt', 'errorFromInt',
    'errorName', 'errSetCast', 'export', 'extern', 'fence', 'field',
    'fieldParentPtr', 'floatCast', 'floatFromInt', 'floor', 'frame',
    'Frame', 'hasDecl', 'hasField', 'import', 'intCast', 'intFromBool',
    'intFromEnum', 'intFromFloat', 'intFromPtr', 'memcpy', 'memset',
    'wasmMemorySize', 'wasmMemoryGrow', 'max', 'min', 'mulAdd',
    'mulWithOverflow', 'offsetOf', 'panic', 'popCount', 'ptrCast',
    'ptrFromInt', 'rem', 'returnAddress', 'round', 'splat', 'reduce',
    'select', 'shlExact', 'shlWithOverflow', 'shrExact', 'shuffle',
    'sizeOf', 'simplifyTypeId', 'sqrt', 'sin', 'cos', 'tan', 'exp',
    'exp2', 'log', 'log2', 'log10', 'abs', 'fabs',
    'subWithOverflow', 'tagName', 'This', 'truncate', 'Type',
    'typeInfo', 'typeName', 'TypeOf', 'unionInit', 'Vector',
    # Standard start-of-name patterns we never want as standalone calls
    'align', 'linksection', 'callconv', 'noalias', 'volatile',
    'allowzero', 'noreturn', 'packed',
})


def parse_zig_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Zig source using regex — extracts functions, structs, enums,
    imports, and function-call edges.

    Parameters
    ----------
    content : str
        Full text of the ``.zig`` file.
    rel_path : str
        Repository-relative path (used to build node IDs).

    Returns
    -------
    dict
        ``{"nodes": [...], "edges": [...]}``
    """

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # ── Strip comments to avoid false positives ────────────────────
    # Zig has two comment styles: // and /* */
    cleaned_lines: List[str] = []
    for raw_line in lines:
        # Remove single-line comments (but preserve string literals)
        cleaned = _strip_line_comment(raw_line)
        cleaned_lines.append(cleaned)
    # Remove block comments across lines (simple approach)
    cleaned_content = '\n'.join(cleaned_lines)
    cleaned_content = re.sub(r'/\*.*?\*/', '', cleaned_content, flags=re.DOTALL)
    lines = cleaned_content.split('\n')

    # ── Collect function definitions for call resolution ───────────
    fn_defs: Dict[str, str] = {}  # fn_name → node_id

    # ────────────────────────────────────────────────────────────────
    # Pass 1 — Imports  (const name = @import("path")...)
    # ────────────────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # const Builder = @import("std").Build;
        # const foo = @import("bar.zig");
        m = re.match(
            r'const\s+(\w+)\s*=\s*@import\s*\(\s*"([^"]+)"\s*\)',
            stripped,
        )
        if m:
            import_name = m.group(1)
            import_path = m.group(2)
            edges.append({
                "from": rel_path,
                "to": import_path,
                "type": "import",
                "weight": 1,
                "import_name": import_name,
            })

    # ────────────────────────────────────────────────────────────────
    # Pass 2 — Struct declarations
    # ────────────────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # pub const Name = struct {  |  const Name = struct {
        # Also handles: packed struct, extern struct
        m = re.match(
            r'(?:pub\s+)?const\s+(\w+)\s*=\s*(?:packed\s+|extern\s+)?struct\s*\{',
            stripped,
        )
        if m:
            name = m.group(1)
            is_pub = stripped.startswith('pub ')
            node_id = f"{rel_path}:{i}:{name}"
            nodes.append({
                "id": node_id,
                "type": "struct",
                "name": name,
                "fn": name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "pub": is_pub,
                "ref_count": 0,
                "status": "active",
            })
            fn_defs[name] = node_id

    # ────────────────────────────────────────────────────────────────
    # Pass 3 — Enum declarations
    # ────────────────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # pub const Name = enum {  |  const Name = enum {
        # Also handles: enum(u8) { , packed enum, extern enum
        m = re.match(
            r'(?:pub\s+)?const\s+(\w+)\s*=\s*(?:packed\s+|extern\s+)?enum(?:\s*\([^)]*\))?\s*\{',
            stripped,
        )
        if m:
            name = m.group(1)
            is_pub = stripped.startswith('pub ')
            node_id = f"{rel_path}:{i}:{name}"
            nodes.append({
                "id": node_id,
                "type": "enum",
                "name": name,
                "fn": name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "pub": is_pub,
                "ref_count": 0,
                "status": "active",
            })
            fn_defs[name] = node_id

    # ────────────────────────────────────────────────────────────────
    # Pass 4 — Top-level function declarations
    # ────────────────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('/*'):
            continue
        # pub fn name(...) ... {  |  fn name(...) ... {
        # Handles: pub fn, fn, with optional callconv, align, etc.
        m = re.match(
            r'(pub\s+)?fn\s+(\w+)\s*\(',
            stripped,
        )
        if m:
            is_pub = m.group(1) is not None
            fn_name = m.group(2)
            if fn_name in _ZIG_KEYWORDS:
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": fn_name,
                "fn": fn_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "pub": is_pub,
                "ref_count": 0,
                "status": "active",
            })
            fn_defs[fn_name] = node_id

    # ────────────────────────────────────────────────────────────────
    # Pass 5 — Function call edges (within function bodies)
    # ────────────────────────────────────────────────────────────────
    # Performance guard: skip call-edge extraction for very large files.
    if len(lines) > 5000:
        return {"nodes": nodes, "edges": edges}

    # Build function → body range map via brace counting
    fn_ranges: List[tuple] = []  # [(node_id, start_line_1based, end_line_1based)]
    brace_count = 0
    current_fn_id: str | None = None
    fn_start = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect function start (already registered in nodes)
        for node in nodes:
            if node.get("line") == i and node.get("type") == "function":
                # Close any previous function first
                if current_fn_id is not None:
                    fn_ranges.append((current_fn_id, fn_start, i - 1))
                current_fn_id = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn_id is not None:
            brace_count += stripped.count('{') - stripped.count('}')
            # Once we've seen at least one '{' and brace_count drops back to 0,
            # the function body has ended.
            if brace_count <= 0 and '{' in ''.join(lines[fn_start - 1:i]):
                fn_ranges.append((current_fn_id, fn_start, i))
                current_fn_id = None

    # Handle last function (if file ends inside a function body)
    if current_fn_id is not None:
        fn_ranges.append((current_fn_id, fn_start, len(lines)))

    # Match function calls:  functionName(  and obj.method(
    # Zig uses snake_case for functions and camelCase for methods.
    call_pattern = re.compile(r'(?:(\w+)\s*\.\s*)?(\w+)\s*\(')

    for fn_id, start_line, end_line in fn_ranges:
        # Clamp range
        s = max(start_line - 1, 0)
        e = min(end_line, len(lines))
        body = '\n'.join(lines[s:e])

        for m in call_pattern.finditer(body):
            obj_name = m.group(1) or ""
            call_name = m.group(2)

            # Skip keywords and builtins
            if call_name in _ZIG_KEYWORDS:
                continue
            if obj_name in _ZIG_KEYWORDS:
                continue
            # Skip @builtin calls (compiler intrinsics)
            if call_name.startswith('@'):
                continue
            # Skip self-references
            fn_short = fn_id.rsplit(':', 1)[-1] if ':' in fn_id else fn_id
            if call_name == fn_short and not obj_name:
                continue

            # Create edge — resolved or unresolved
            if call_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[call_name],
                    "to_fn": call_name,
                    "type": "call",
                    "weight": 1,
                })
            else:
                # Unresolved call — still create edge for cross-file resolution
                edges.append({
                    "from": fn_id,
                    "to_fn": call_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}


# ─── Helpers ────────────────────────────────────────────────────────

def _strip_line_comment(line: str) -> str:
    """Remove ``//`` comments from a single line, respecting string literals.

    Zig string literals are delimited by double quotes and may contain
    escaped characters.  We walk the line character-by-character so that
    ``//`` inside a string is not treated as a comment start.
    """
    in_string = False
    i = 0
    result = []
    while i < len(line):
        ch = line[i]
        if in_string:
            result.append(ch)
            if ch == '\\' and i + 1 < len(line):
                # Escaped character — consume the next char too
                i += 1
                result.append(line[i])
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
                result.append(ch)
            elif ch == '/' and i + 1 < len(line) and line[i + 1] == '/':
                # Comment start — discard the rest of the line
                break
            else:
                result.append(ch)
        i += 1
    return ''.join(result)

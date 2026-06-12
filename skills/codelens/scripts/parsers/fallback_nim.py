"""
Fallback Nim Parser for CodeLens — regex-based extraction.
Extracts procs, funcs, methods, iterators, templates, macros, types,
imports, exports, and function call relationships for edge resolution.

Nim syntax overview:
- proc name*(params): returnType = body     (function, * = exported)
- func name*(params): returnType = body     (pure function)
- method name(params): returnType = body    (method, dynamic dispatch)
- iterator name(params): returnType = body  (iterator)
- template name(params): untyped = body     (template, hygienic macro)
- macro name(params): untyped = body        (macro)
- type Name = object/ref object/enum        (type definitions)
- import module / from module import x      (imports)
- const/let/var NAME                        (declarations)
- when isMainModule:                        (entry point guard)
"""

import re
from typing import Dict, List, Any


def parse_nim_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Nim source using regex — extracts procs, funcs, types, imports, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # ─── Imports ───────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith('#'):
            continue
        # import module1, module2
        m = re.match(r'import\s+(.+?)(?:\s*,\s*)?$', stripped)
        if m:
            imports_str = m.group(1)
            # Split by comma for multiple imports
            for imp in imports_str.split(','):
                imp = imp.strip()
                if imp:
                    # Handle "module except symbol" and "module as alias"
                    imp = imp.split(' except ')[0].split(' as ')[0].strip()
                    edges.append({"from": rel_path, "to": imp, "type": "import", "weight": 1})
            continue
        # from module import symbol1, symbol2
        m = re.match(r'from\s+(\w[\w/]*)\s+import\s+(.+?)$', stripped)
        if m:
            mod_name = m.group(1).strip()
            edges.append({"from": rel_path, "to": mod_name, "type": "import", "weight": 1})
            continue
        # export module
        m = re.match(r'export\s+(\w[\w/]*)', stripped)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})
            continue
        # include module (textual include, different from import)
        m = re.match(r'include\s+(\w[\w/]*)', stripped)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "include", "weight": 1})

    # ─── Collect function/proc names for call resolution ──────────
    fn_defs = {}  # fn_name -> node_id

    # ─── Procs / Funcs / Methods / Iterators / Templates / Macros ─
    _NIM_PROC_PATTERNS = [
        # Pattern for various Nim procedure-like declarations
        # Handles: proc name*, proc name(params), proc name*(params)
        (re.compile(
            r'^\s*(proc|func|method|iterator|template|macro)\s+'
            r'(`[\w]+`|[\w]+)\s*'   # name (can be backtick-quoted)
            r'[\*]?'                 # optional export marker
            r'\s*[\(\<]',            # must be followed by ( or < (for generics)
        ), True),
        # Simple proc without params: proc name* =
        (re.compile(
            r'^\s*(proc|func|method|iterator|template|macro)\s+'
            r'(`[\w]+`|[\w]+)\s*'
            r'[\*]?'                 # optional export marker
            r'\s*=',
        ), False),
    ]

    _TYPE_MAP = {
        "proc": "function",
        "func": "function",
        "method": "method",
        "iterator": "iterator",
        "template": "template",
        "macro": "macro",
    }

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith('#'):
            continue

        for pattern, _has_params in _NIM_PROC_PATTERNS:
            m = pattern.match(stripped)
            if m:
                kind = m.group(1)
                raw_name = m.group(2).strip('`')
                ntype = _TYPE_MAP.get(kind, "function")
                is_exported = '*' in stripped[:stripped.index(raw_name) + len(raw_name) + 1] if raw_name in stripped else False
                node_id = f"{rel_path}:{i}:{raw_name}"
                node = {
                    "id": node_id,
                    "type": ntype,
                    "name": raw_name,
                    "fn": raw_name,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                }
                if is_exported:
                    node["exported"] = True
                nodes.append(node)
                fn_defs[raw_name] = node_id
                break

    # ─── Type definitions ─────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        # type Name = object / ref object / ptr object
        m = re.match(r'^\s*type\s+([\w]+)\s*[\*]?\s*=\s*(ref\s+)?(ptr\s+)?object\b', stripped)
        if m:
            type_name = m.group(1)
            is_ref = m.group(2) is not None
            ntype = "class" if is_ref else "struct"
            nodes.append({
                "id": f"{rel_path}:{i}:{type_name}",
                "type": ntype,
                "name": type_name,
                "fn": type_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            fn_defs[type_name] = f"{rel_path}:{i}:{type_name}"
            continue

        # type Name = enum
        m = re.match(r'^\s*type\s+([\w]+)\s*[\*]?\s*=\s*enum\b', stripped)
        if m:
            type_name = m.group(1)
            nodes.append({
                "id": f"{rel_path}:{i}:{type_name}",
                "type": "enum",
                "name": type_name,
                "fn": type_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            continue

        # type Name = distinct ...
        m = re.match(r'^\s*type\s+([\w]+)\s*[\*]?\s*=\s*distinct\b', stripped)
        if m:
            type_name = m.group(1)
            nodes.append({
                "id": f"{rel_path}:{i}:{type_name}",
                "type": "type_alias",
                "name": type_name,
                "fn": type_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            continue

        # type Name = SomeType (type alias)
        m = re.match(r'^\s*type\s+([\w]+)\s*[\*]?\s*=\s*([A-Z]\w*)', stripped)
        if m:
            type_name = m.group(1)
            alias_target = m.group(2)
            nodes.append({
                "id": f"{rel_path}:{i}:{type_name}",
                "type": "type_alias",
                "name": type_name,
                "fn": type_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "alias_of": alias_target,
            })
            continue

    # ─── Const / Let / Var (module-level) ─────────────────────────
    # Only detect top-level (no indentation) declarations
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        # Only module-level: no leading whitespace (or minimal)
        if line and line[0] not in (' ', '\t'):
            m = re.match(r'^(const|let|var)\s+([\w]+)\s*[\*]?', stripped)
            if m:
                kind = m.group(1)
                var_name = m.group(2)
                # Skip if already defined as proc/type
                if var_name in fn_defs:
                    continue
                ntype = "constant" if kind == "const" else "variable"
                nodes.append({
                    "id": f"{rel_path}:{i}:{var_name}",
                    "type": ntype,
                    "name": var_name,
                    "fn": var_name,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                })

    # ─── when isMainModule ────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r'^\s*when\s+isMainModule\s*:', stripped):
            nodes.append({
                "id": f"{rel_path}:{i}:isMainModule",
                "type": "entrypoint",
                "name": "isMainModule",
                "fn": "isMainModule",
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "label": "nim_main_guard",
            })
            break  # Only one per file

    # ─── Function call edges ──────────────────────────────────────
    # Extract call relationships within proc bodies.
    # Match: fnName(...), obj.method(...), module.fn(...)
    # Skip: keywords, builtins, type conversions

    _NIM_KEYWORDS = frozenset({
        'if', 'elif', 'else', 'for', 'while', 'case', 'of', 'when',
        'try', 'except', 'finally', 'block', 'defer', 'return', 'yield',
        'raise', 'discard', 'break', 'continue', 'asm', 'proc', 'func',
        'method', 'iterator', 'template', 'macro', 'type', 'const',
        'let', 'var', 'import', 'from', 'export', 'include', 'converter',
        'bind', 'mixin', 'using', 'addr', 'cast', 'ref', 'ptr',
        'object', 'enum', 'tuple', 'array', 'seq', 'set', 'range',
    })
    _NIM_BUILTINS = frozenset({
        'echo', 'new', 'newSeq', 'high', 'low', 'len', 'inc', 'dec',
        'add', 'del', 'contains', 'items', 'pairs', 'mpairs',
        'assert', 'doAssert', 'debugEcho', 'quit', 'fatal',
        'alloc', 'alloc0', 'dealloc', 'realloc', 'resize',
        'zeroMem', 'copyMem', 'moveMem', 'equalMem',
        'open', 'close', 'read', 'write', 'readLine', 'readFile', 'writeFile',
        'parseInt', 'parseFloat', 'toString', 'repr', 'type', 'typeof',
        'sizeof', 'offsetof', 'compiledAt', 'astToStr',
        'gcd', 'lcm', 'clamp', 'abs', 'min', 'max', 'sum',
        'map', 'filter', 'foldl', 'foldr', 'apply', 'keepIf', 'delete',
        'insert', 'pop', 'sort', 'sorted', 'reverse',
        'find', 'replace', 'split', 'join', 'strip', 'startsWith', 'endsWith',
        'format', 'formatFloat', 'formatBiggestFloat',
        'toUpper', 'toLower', 'capitalize', 'normalize',
        'initSet', 'initHashSet', 'initOrderedSet', 'initTable', 'initOrderedTable',
        'initCountTable', 'initDeque', 'initHeapQueue',
        'sleep', 'getCurrentTime', 'getTime', 'cpuTime', 'epochTime',
        'getEnv', 'existsEnv', 'putEnv', 'getAppDir', 'getAppFilename',
        'getCurrentDir', 'setCurrentDir', 'existsFile', 'existsDir',
        'createDir', 'removeDir', 'copyFile', 'moveFile', 'removeFile',
        'walkDir', 'walkFiles', 'walkDirs', 'walkRec',
        'execCmd', 'execCmdEx', 'startProcess', 'waitForExit',
        'newException', 'getCurrentException', 'getCurrentExceptionMsg',
        'onRaise',
        # Common macro/template patterns
        'await', 'spawn', 'parallel', 'deepCopy',
    })
    # Standard library prefixes to skip for call resolution
    _NIM_STD_PREFIXES = frozenset({
        'system', 'std', 'os', 'strutils', 'sequtils', 'math',
        'strformat', 'json', 'xmltree', 'xmlparser', 'httpclient',
        'asynchttpserver', 'asyncdispatch', 'asyncfutures', 'net',
        'times', 'osproc', 'streams', 'tables', 'sets', 'critbits',
        'deques', 'heapqueue', 'intsets', 'lists', 'queues',
        'ropes', 'sets', 'unittest', 'parseopt', 'parsecfg',
        'parseutils', 'parsesql', 'pegs', 'regex', 're',
        'terminal', 'colors', 'logging', 'threadpool',
    })

    # Build function→body range map using indentation-based block tracking
    fn_ranges = []  # [(node_id, start_line, end_line)]
    current_fn = None
    fn_start = 0
    fn_base_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Check if this line starts a new function
        for node in nodes:
            if node.get("line") == i and node.get("type") in (
                "function", "method", "iterator", "template", "macro"
            ):
                # End previous function
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                # Calculate base indentation of the proc body
                fn_base_indent = len(line) - len(line.lstrip())
                break

        if current_fn and stripped:
            # In Nim, a block ends when we return to the same or lesser indentation
            # than the proc definition line (and we're past the signature)
            current_indent = len(line) - len(line.lstrip())
            # The body should be more indented than the proc line
            if i > fn_start + 1 and current_indent <= fn_base_indent and stripped:
                # Check if this is a new top-level declaration
                if not stripped.startswith(('#', ' ', '\t', ':', '.', ',')):
                    # Might be end of block
                    if re.match(r'(proc|func|method|iterator|template|macro|type|const|let|var|import|from|export|include)\s', stripped):
                        fn_ranges.append((current_fn, fn_start, i - 1))
                        current_fn = None

    # Handle last function
    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    call_pattern = re.compile(
        r'(?<![.\w])'                           # Not preceded by dot or identifier
        r'((?:[\w]+\.)*[\w]+)\s*\('              # fnName( or obj.method( or pkg.fn(
    )

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            call_expr = m.group(1)
            parts = call_expr.split('.')
            leaf_name = parts[-1]

            # Skip keywords and builtins
            if leaf_name in _NIM_KEYWORDS or leaf_name in _NIM_BUILTINS:
                continue
            # Skip type-like calls (PascalCase with no known definition)
            # Actually we should NOT skip these - they could be constructors

            if leaf_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[leaf_name],
                    "to_fn": leaf_name,
                    "type": "call",
                    "weight": 1,
                })
            else:
                # Unresolved call — still create edge for cross-file resolution
                edges.append({
                    "from": fn_id,
                    "to_fn": leaf_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}

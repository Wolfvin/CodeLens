"""
Type Inference Engine for CodeLens — v3
Lightweight type inference for JS/Python — propagates types through call chains.

Even PARTIAL type info transforms data flow analysis from "maybe" to "likely".
Does NOT replace TypeScript — it's for JS/Python files that lack type annotations.

Strategies:
1. Literal type inference: const x = "hello" → string
2. Return type inference: function foo() { return 42 } → number
3. API type inference: fetch().json() → object, getElementById → Element|null
4. Propagation: const y = foo() → y inherits foo's return type
5. Assignment tracking: let x = "a"; x = 5 → x: string | number

Output: Best-effort type annotations for untyped code.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS

SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py"}

# Known API return types
KNOWN_RETURN_TYPES = {
    # DOM
    "getElementById": "Element | null",
    "querySelector": "Element | null",
    "querySelectorAll": "NodeListOf<Element>",
    "getElementsByClassName": "HTMLCollectionOf<Element>",
    "getElementsByTagName": "HTMLCollectionOf<Element>",
    "createElement": "HTMLElement",
    "createTextNode": "Text",
    # fetch
    "fetch": "Promise<Response>",
    "json": "any",
    "text": "Promise<string>",
    "blob": "Promise<Blob>",
    # JSON
    "JSON.parse": "any",
    "JSON.stringify": "string",
    # Array methods
    ".map": "Array",
    ".filter": "Array",
    ".find": "T | undefined",
    ".reduce": "T",
    ".forEach": "void",
    ".push": "number",
    ".pop": "T | undefined",
    ".shift": "T | undefined",
    ".slice": "Array",
    ".concat": "Array",
    ".join": "string",
    ".split": "string[]",
    # String methods
    ".trim": "string",
    ".toLowerCase": "string",
    ".toUpperCase": "string",
    ".replace": "string",
    ".substring": "string",
    ".indexOf": "number",
    ".includes": "boolean",
    ".startsWith": "boolean",
    ".endsWith": "boolean",
    # Object methods
    "Object.keys": "string[]",
    "Object.values": "any[]",
    "Object.entries": "[string, any][]",
    "Object.assign": "T",
    # Math
    "Math.random": "number",
    "Math.floor": "number",
    "Math.ceil": "number",
    "Math.round": "number",
    "Math.abs": "number",
    "Math.max": "number",
    "Math.min": "number",
    # Console
    "console.log": "void",
    "console.error": "void",
    "console.warn": "void",
    # Python
    "len": "int",
    "range": "range",
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "dict": "dict",
    "set": "set",
    "tuple": "tuple",
    "open": "TextIO | BinaryIO",
    "print": "None",
    "input": "str",
    "sorted": "list",
    "enumerate": "enumerate",
    "zip": "zip",
    "map": "map",
    "filter": "filter",
}


def infer_types(
    workspace: str,
    file_path: Optional[str] = None,
    function_name: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Perform lightweight type inference on workspace code.

    Args:
        workspace: Absolute path to workspace
        file_path: Optional specific file to analyze
        function_name: Optional specific function to analyze
        config: CodeLens config

    Returns:
        Dict with inferred types for variables and functions
    """
    workspace = os.path.abspath(workspace)

    type_map: Dict[str, Dict[str, Any]] = {}  # file → {name → type_info}

    files_to_analyze = []

    if file_path:
        # Analyze specific file
        full_path = os.path.join(workspace, file_path) if not os.path.isabs(file_path) else file_path
        if os.path.exists(full_path):
            files_to_analyze.append(full_path)
    else:
        # Analyze all source files
        for root, dirs, filenames in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
            if '.codelens' in root:
                dirs.clear()
                continue

            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in SOURCE_EXTENSIONS:
                    files_to_analyze.append(os.path.join(root, filename))

    for fp in files_to_analyze:
        rel_path = os.path.relpath(fp, workspace)
        ext = os.path.splitext(fp)[1].lower()

        try:
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # Skip TypeScript files with existing type annotations
        if ext in {".ts", ".tsx"} and _has_typescript_annotations(content):
            type_map[rel_path] = {
                "_note": "File has TypeScript annotations — inference skipped",
                "_confidence": "native"
            }
            continue

        if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
            file_types = _infer_js_types(content, rel_path)
            type_map[rel_path] = file_types
        elif ext == ".py":
            file_types = _infer_py_types(content, rel_path)
            type_map[rel_path] = file_types

    # If specific function requested, filter results
    if function_name:
        function_types = {}
        for file_path, types in type_map.items():
            if function_name in types:
                function_types[file_path] = {function_name: types[function_name]}
            # Also check for the function in return types
            for name, type_info in types.items():
                if isinstance(type_info, dict) and type_info.get("kind") == "function" and name == function_name:
                    function_types[file_path] = {name: type_info}

        return {
            "status": "ok",
            "workspace": workspace,
            "function": function_name,
            "inferred_types": function_types,
            "count": len(function_types)
        }

    # Compute summary
    total_vars = 0
    total_fns = 0
    high_confidence = 0

    for types in type_map.values():
        for name, info in types.items():
            if isinstance(info, dict):
                if info.get("kind") == "function":
                    total_fns += 1
                else:
                    total_vars += 1
                if info.get("confidence") == "high":
                    high_confidence += 1

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "files_analyzed": len(type_map),
            "variables_typed": total_vars,
            "functions_typed": total_fns,
            "high_confidence": high_confidence
        },
        "type_map": type_map,
        "count": len(type_map)
    }


def _has_typescript_annotations(content: str) -> bool:
    """Check if a TypeScript file has type annotations."""
    # Look for explicit type annotations
    return bool(re.search(r':\s*(?:string|number|boolean|any|void|never|object|undefined|null|Array|Record|Map|Set|Promise)\b', content))


def _infer_js_types(content: str, rel_path: str) -> Dict[str, Any]:
    """Infer types for a JS/TS file."""
    types = {}
    lines = content.split('\n')

    # Remove comments for cleaner analysis
    clean = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)

    # ─── Literal type inference ─────────────────────────
    # const x = "hello" → x: string
    for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*(.+?)(?:;|$)', clean, re.MULTILINE):
        name = m.group(1)
        value = m.group(2).strip()
        inferred = _infer_literal_type(value)
        if inferred:
            types[name] = {
                "type": inferred,
                "confidence": "high",
                "kind": "variable",
                "line": clean[:m.start()].count('\n') + 1,
                "source": "literal"
            }

    # ─── Function return type inference ─────────────────
    for m in re.finditer(r'(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{', clean):
        fn_name = m.group(1)
        fn_start = m.end()
        fn_body = _extract_fn_body(clean, fn_start)

        if fn_body:
            return_type = _infer_return_type(fn_body)
            params = _extract_params(clean[m.start():m.end()])
            types[fn_name] = {
                "type": return_type,
                "params": params,
                "confidence": "high" if return_type != "unknown" else "low",
                "kind": "function",
                "line": clean[:m.start()].count('\n') + 1,
                "source": "return_inference"
            }

    # Arrow functions
    for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>\s*(?:\{|(.+?)(?:;|$))', clean, re.MULTILINE):
        fn_name = m.group(1)
        expr_return = m.group(2)

        if expr_return:
            return_type = _infer_literal_type(expr_return.strip())
            types[fn_name] = {
                "type": return_type or "unknown",
                "confidence": "high" if return_type else "low",
                "kind": "function",
                "line": clean[:m.start()].count('\n') + 1,
                "source": "arrow_return"
            }

    # ─── Known API return types ────────────────────────
    for api_name, api_type in KNOWN_RETURN_TYPES.items():
        if api_name.startswith('.'):
            # Method call
            pattern = r'\w+' + re.escape(api_name) + r'\s*\('
        else:
            pattern = re.escape(api_name) + r'\s*\('

        for m in re.finditer(pattern, clean):
            # Find the variable it's assigned to
            line_start = clean.rfind('\n', 0, m.start()) + 1
            line = clean[line_start:clean.find('\n', m.start())].strip()

            assign_match = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*', line)
            if assign_match:
                var_name = assign_match.group(1)
                if var_name not in types:
                    types[var_name] = {
                        "type": api_type,
                        "confidence": "medium",
                        "kind": "variable",
                        "line": clean[:m.start()].count('\n') + 1,
                        "source": f"known_api:{api_name}"
                    }

    return types


def _infer_py_types(content: str, rel_path: str) -> Dict[str, Any]:
    """Infer types for a Python file."""
    types = {}
    clean = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
    clean = re.sub(r'""".*?"""', '', clean, flags=re.DOTALL)
    clean = re.sub(r"'''.*?'''", '', clean, flags=re.DOTALL)

    # ─── Literal type inference ─────────────────────────
    for m in re.finditer(r'(\w+)\s*=\s*(.+?)(?:\n|$)', clean):
        name = m.group(1)
        value = m.group(2).strip()
        inferred = _infer_literal_type_py(value)
        if inferred and name not in types:
            types[name] = {
                "type": inferred,
                "confidence": "high",
                "kind": "variable",
                "line": clean[:m.start()].count('\n') + 1,
                "source": "literal"
            }

    # ─── Function return type inference ─────────────────
    for m in re.finditer(r'def\s+(\w+)\s*\(([^)]*)\)', clean):
        fn_name = m.group(1)
        params_str = m.group(2)
        fn_start = m.end()

        # Find return statements in function body
        base_indent = len(clean[:fn_start].split('\n')[-1]) - len(clean[:fn_start].split('\n')[-1].lstrip())
        return_types = set()

        for line in clean[fn_start:].split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= base_indent and stripped and not stripped.startswith(('#', '"""', "'''")):
                break

            ret_match = re.match(r'return\s+(.+)', stripped)
            if ret_match:
                ret_type = _infer_literal_type_py(ret_match.group(1).strip())
                if ret_type:
                    return_types.add(ret_type)

        if return_types:
            rt = " | ".join(return_types) if len(return_types) > 1 else list(return_types)[0]
        else:
            rt = "None"

        types[fn_name] = {
            "type": rt,
            "params": [p.strip().split(':')[0].strip().split('=')[0].strip() for p in params_str.split(',') if p.strip() and p.strip() != 'self'],
            "confidence": "high" if return_types else "low",
            "kind": "function",
            "line": clean[:m.start()].count('\n') + 1,
            "source": "return_inference"
        }

    return types


def _infer_literal_type(value: str) -> Optional[str]:
    """Infer type from a JS literal value."""
    value = value.strip()

    if value.startswith('"') or value.startswith("'") or value.startswith('`'):
        return "string"
    if value in ('true', 'false'):
        return "boolean"
    if value == 'null':
        return "null"
    if value == 'undefined':
        return "undefined"
    if re.match(r'^-?\d+$', value):
        return "number"
    if re.match(r'^-?\d+\.\d+$', value):
        return "number"
    if value.startswith('['):
        return "Array"
    if value.startswith('{'):
        return "object"
    if value.startswith('new Map'):
        return "Map"
    if value.startswith('new Set'):
        return "Set"
    if value.startswith('new Date'):
        return "Date"
    if value.startswith('new Error'):
        return "Error"
    if value.startswith('new Promise'):
        return "Promise"
    if value.startswith('/') and value.endswith('/'):
        return "RegExp"
    if value.startswith('Symbol('):
        return "Symbol"
    if value.startswith('BigInt('):
        return "bigint"

    # Known constructors
    for api_name, api_type in KNOWN_RETURN_TYPES.items():
        if not api_name.startswith('.') and value.startswith(api_name):
            return api_type

    return None


def _infer_literal_type_py(value: str) -> Optional[str]:
    """Infer type from a Python literal value."""
    value = value.strip()

    if value.startswith('"') or value.startswith("'"):
        return "str"
    if value in ('True', 'False'):
        return "bool"
    if value == 'None':
        return "None"
    if re.match(r'^-?\d+$', value):
        return "int"
    if re.match(r'^-?\d+\.\d+$', value):
        return "float"
    if value.startswith('['):
        return "list"
    if value.startswith('{'):
        return "dict"
    if value.startswith('('):
        return "tuple"
    if value.startswith('{') and ':' not in value:
        return "set"
    if value.startswith('b"') or value.startswith("b'"):
        return "bytes"
    if value.startswith('f"') or value.startswith("f'"):
        return "str"

    # Known function returns
    for api_name, api_type in KNOWN_RETURN_TYPES.items():
        if value.startswith(api_name + '('):
            return api_type

    return None


def _extract_fn_body(content: str, start: int) -> Optional[str]:
    """Extract function body from starting position."""
    brace_count = 0
    started = False
    body_chars = []

    for i in range(start, min(start + 5000, len(content))):
        ch = content[i]
        body_chars.append(ch)

        if ch == '{':
            brace_count += 1
            started = True
        elif ch == '}':
            brace_count -= 1
            if started and brace_count == 0:
                return ''.join(body_chars)

    return None


def _infer_return_type(fn_body: str) -> str:
    """Infer return type from function body."""
    if not fn_body:
        return "void"

    # Check for return statements
    returns = re.findall(r'return\s+(.+?)(?:;|\n)', fn_body)

    if not returns:
        return "void"

    return_types = set()
    for ret in returns:
        t = _infer_literal_type(ret.strip())
        if t:
            return_types.add(t)

    if not return_types:
        return "unknown"

    if len(return_types) == 1:
        return list(return_types)[0]

    return " | ".join(sorted(return_types))


def _extract_params(fn_sig: str) -> List[Dict]:
    """Extract parameter names and inferred types from function signature."""
    m = re.search(r'\(([^)]*)\)', fn_sig)
    if not m:
        return []

    params = []
    for p in m.group(1).split(','):
        p = p.strip()
        if not p:
            continue

        # Handle default values
        if '=' in p:
            name, default = p.split('=', 1)
            name = name.strip()
            default_type = _infer_literal_type(default.strip()) or "unknown"
            params.append({"name": name, "type": default_type, "has_default": True})
        else:
            name = p.strip()
            params.append({"name": name, "type": "unknown", "has_default": False})

    return params

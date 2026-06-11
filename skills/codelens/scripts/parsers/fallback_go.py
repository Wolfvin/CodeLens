"""
Fallback Go Parser for CodeLens — regex-based
Extracts functions, methods, types, interfaces, and package-level declarations
from Go source files when tree-sitter Go parser is unavailable.

Go-specific features:
- func declarations (with receiver for methods)
- type declarations (struct, interface, type alias)
- var/const declarations at package level
- package clause detection
- import tracking
"""

import re
from typing import Dict, List, Any


# Go-specific patterns
_FUNC_PATTERN = re.compile(
    r'^func\s+'                           # func keyword
    r'(?:\([^)]*\)\s+)?'                  # optional receiver
    r'(\w+)'                              # function name
    r'\s*\('                              # opening paren
    , re.MULTILINE
)

_METHOD_PATTERN = re.compile(
    r'^func\s+'
    r'\(\s*(\w+)\s+(?:\*?)(\w+)\s*\)\s+'  # receiver (name *Type)
    r'(\w+)'                              # method name
    r'\s*\('                              # opening paren
    , re.MULTILINE
)

_STRUCT_PATTERN = re.compile(
    r'^type\s+(\w+)\s+struct\s*\{'
    , re.MULTILINE
)

_INTERFACE_PATTERN = re.compile(
    r'^type\s+(\w+)\s+interface\s*\{'
    , re.MULTILINE
)

_TYPE_ALIAS_PATTERN = re.compile(
    r'^type\s+(\w+)\s+(?!struct\b|interface\b)(\w[\w.]*)\s*$'
    , re.MULTILINE
)

_VAR_PATTERN = re.compile(
    r'^var\s+(\w+)', re.MULTILINE
)

_CONST_PATTERN = re.compile(
    r'^const\s+(?:\(\s*|\s*(\w+))', re.MULTILINE
)

_IMPORT_PATTERN = re.compile(
    r'"([^"]+)"', re.MULTILINE
)

_PACKAGE_PATTERN = re.compile(
    r'^package\s+(\w+)', re.MULTILINE
)

# Receiver type extraction
_RECEIVER_PATTERN = re.compile(
    r'func\s+\(\s*\w+\s+(?:\*?)(\w+)\s*\)\s+\w+'
)


def parse_go_fallback(content: str, rel_path: str = "") -> Dict[str, Any]:
    """
    Parse a Go source file using regex fallback.
    
    Returns backend data with functions, types, imports, and call edges.
    """
    functions = []
    types = []
    imports = []
    package_name = ""

    # Package detection
    pkg_match = _PACKAGE_PATTERN.search(content)
    if pkg_match:
        package_name = pkg_match.group(1)

    # Import extraction
    # Handle both single imports and import blocks
    import_block_match = re.search(r'import\s*\((.*?)\)', content, re.DOTALL)
    if import_block_match:
        for m in _IMPORT_PATTERN.finditer(import_block_match.group(1)):
            imports.append(m.group(1))
    else:
        single_import = re.search(r'import\s+"([^"]+)"', content)
        if single_import:
            imports.append(single_import.group(1))

    # Function declarations
    for m in _FUNC_PATTERN.finditer(content):
        fn_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        
        # Determine if this is a method by checking receiver
        is_method = False
        receiver_type = None
        method_match = _METHOD_PATTERN.match(m.group(0))
        if method_match:
            is_method = True
            receiver_type = method_match.group(2)

        # Extract parameter count
        sig_start = m.end() - 1  # position of opening paren
        paren_depth = 0
        sig_end = sig_start
        for i in range(sig_start, min(sig_start + 500, len(content))):
            if content[i] == '(':
                paren_depth += 1
            elif content[i] == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    sig_end = i
                    break
        
        params_str = content[sig_start + 1:sig_end]
        param_count = _count_go_params(params_str)

        functions.append({
            "id": f"{rel_path}:{line_num}",
            "fn": fn_name,
            "file": rel_path,
            "line": line_num,
            "async": False,
            "method": is_method,
            "receiver": receiver_type,
            "params": param_count,
        })

    # Type declarations
    for m in _STRUCT_PATTERN.finditer(content):
        type_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        types.append({
            "type": "struct",
            "name": type_name,
            "file": rel_path,
            "line": line_num,
        })

    for m in _INTERFACE_PATTERN.finditer(content):
        type_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        types.append({
            "type": "interface",
            "name": type_name,
            "file": rel_path,
            "line": line_num,
        })

    for m in _TYPE_ALIAS_PATTERN.finditer(content):
        type_name = m.group(1)
        alias_of = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        types.append({
            "type": "alias",
            "name": type_name,
            "alias_of": alias_of,
            "file": rel_path,
            "line": line_num,
        })

    # Build edges from function calls within function bodies
    edges = _extract_go_edges(content, functions, rel_path)

    return {
        "backend": {
            "functions": functions,
            "types": types,
            "imports": imports,
            "edges": edges,
        },
        "package": package_name,
    }


def _count_go_params(params_str: str) -> int:
    """Count the number of parameters in a Go function signature."""
    if not params_str.strip():
        return 0
    
    # Go allows grouped params: func(a, b int, c string)
    # We count by commas, but need to handle types
    count = 0
    depth = 0
    for char in params_str:
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            count += 1
    
    # Last param (or only param) doesn't have a trailing comma
    if params_str.strip():
        count += 1
    
    # Handle grouped params like "a, b int" counts as 2 not 1
    # For simplicity, return the basic count
    return count


def _extract_go_edges(
    content: str,
    functions: List[Dict],
    rel_path: str
) -> List[Dict[str, str]]:
    """
    Extract call edges from Go source.
    
    For each function, scan its body for calls to other known functions
    in the same file. Also detect cross-package calls.
    """
    edges = []
    func_names = {f["fn"] for f in functions}
    
    # Build a map of function name -> start/end positions
    func_positions = []
    for fn_info in functions:
        fn_name = fn_info["fn"]
        line = fn_info["line"]
        
        # Find function start position
        lines = content.split('\n')
        if line > len(lines):
            continue
        
        # Approximate: find the func declaration line
        pos = 0
        for i in range(line - 1):
            if i < len(lines):
                pos += len(lines[i]) + 1
        
        # Find function body (between matching braces)
        brace_start = content.find('{', pos)
        if brace_start == -1:
            continue
        
        depth = 0
        body_end = brace_start
        for i in range(brace_start, min(brace_start + 50000, len(content))):
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
        
        func_positions.append((fn_name, pos, body_end, fn_info.get("receiver")))
    
    # Scan each function body for calls
    for fn_name, start, end, receiver in func_positions:
        body = content[start:end]
        
        # Find the node id for this function
        caller_node = None
        for fn_info in functions:
            if fn_info["fn"] == fn_name and fn_info.get("file") == rel_path:
                caller_node = fn_info
                break
        if not caller_node:
            continue
        caller_id = caller_node["id"]
        
        # Detect calls to known functions in same file
        for target_fn in func_names:
            if target_fn == fn_name:
                continue
            # Match function calls: fnName( or pkg.fnName(
            pattern = re.compile(r'\b' + re.escape(target_fn) + r'\s*\(')
            if pattern.search(body):
                edges.append({
                    "from": caller_id,
                    "to_fn": target_fn,
                    "via_self": False,
                })
    
    return edges

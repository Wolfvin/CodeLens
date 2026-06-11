"""
Fallback PHP Parser for CodeLens — Regex-based
Parses PHP files for functions, classes, methods, imports (use statements),
constants, traits, and interfaces.

Why a fallback? tree-sitter-php may not be installed in all environments.
This regex parser provides reasonable coverage for the most common PHP constructs
and gracefully degrades on edge cases.

Supports:
- Functions (named, anonymous as closures)
- Classes (with methods, properties, constants)
- Interfaces
- Traits
- Namespace declarations
- Use/import statements (class, function, constant)
- Class method visibility (public, private, protected, static)
- Laravel-specific patterns (Artisan commands, middleware, Eloquent models)
"""

import re
from typing import Dict, List, Any, Optional


def parse_php_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """
    Parse PHP source code using regex fallback.

    Args:
        content: PHP source code string
        rel_path: Relative path from workspace root

    Returns:
        Dict with keys:
        - nodes: List of backend node dicts (functions, classes, etc.)
        - edges: List of edge dicts (call relationships, imports)
        - namespace: Current namespace (or empty string)
        - uses: List of imported symbols
        - laravel: Optional dict with Laravel-specific metadata
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # ─── Namespace ──────────────────────────────────────────
    namespace = ""
    ns_match = re.search(r'namespace\s+([\w\\]+)\s*;', content)
    if ns_match:
        namespace = ns_match.group(1).strip('\\')

    # ─── Use statements (imports) ───────────────────────────
    uses: List[Dict[str, str]] = []
    use_pattern = re.compile(
        r'use\s+'
        r'(?:'
        r'(?:function|const)\s+'       # use function / use const
        r')?'
        r'([\w\\]+)'                    # The imported symbol path
        r'(?:\s+as\s+(\w+))?'          # Optional alias
        r'\s*;'
    )
    for m in use_pattern.finditer(content):
        import_path = m.group(1)
        alias = m.group(2) or import_path.rsplit('\\', 1)[-1]
        line = _line_of(content, m.start())

        uses.append({"name": alias, "full_path": import_path})

        edges.append({
            "from": f"{rel_path}:{line}",
            "to": import_path,
            "type": "import",
            "import_alias": alias
        })

    # ─── Group use statements (PHP 7+) ─────────────────────
    # use Namespace\{ClassA, ClassB as B, Sub\ClassC};
    group_use_pattern = re.compile(
        r'use\s+([\w\\]+)\\{'
        r'([^}]+)'
        r'}\s*;'
    )
    for m in group_use_pattern.finditer(content):
        base_ns = m.group(1)
        group_body = m.group(2)
        line = _line_of(content, m.start())

        for item in re.finditer(r'([\w\\]+)(?:\s+as\s+(\w+))?', group_body):
            import_path = base_ns + '\\' + item.group(1)
            alias = item.group(2) or item.group(1).rsplit('\\', 1)[-1]
            uses.append({"name": alias, "full_path": import_path})
            edges.append({
                "from": f"{rel_path}:{line}",
                "to": import_path,
                "type": "import",
                "import_alias": alias
            })

    # ─── Interface declarations ─────────────────────────────
    iface_pattern = re.compile(
        r'(?:^|\n)\s*interface\s+(\w+)'
        r'(?:\s+extends\s+([\w\\,\s]+))?'
        r'\s*\{',
        re.MULTILINE
    )
    for m in iface_pattern.finditer(content):
        name = m.group(1)
        line = _line_of(content, m.start())
        extends = [e.strip().strip('\\') for e in m.group(2).split(',')] if m.group(2) else []

        node_id = _make_id(rel_path, line, name)
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "interface",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "extends": extends,
        })

        for parent in extends:
            edges.append({
                "from": node_id,
                "to": parent,
                "type": "implements"
            })

    # ─── Trait declarations ─────────────────────────────────
    trait_pattern = re.compile(
        r'(?:^|\n)\s*trait\s+(\w+)\s*\{',
        re.MULTILINE
    )
    for m in trait_pattern.finditer(content):
        name = m.group(1)
        line = _line_of(content, m.start())

        node_id = _make_id(rel_path, line, name)
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "trait",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
        })

    # ─── Class declarations ─────────────────────────────────
    class_pattern = re.compile(
        r'(?:^|\n)\s*(?:abstract\s+|final\s+)*class\s+(\w+)'
        r'(?:\s+extends\s+([\w\\]+))?'
        r'(?:\s+implements\s+([\w\\,\s]+))?'
        r'\s*\{',
        re.MULTILINE
    )
    for m in class_pattern.finditer(content):
        name = m.group(1)
        line = _line_of(content, m.start())
        extends = m.group(2).strip('\\') if m.group(2) else None
        implements = [i.strip().strip('\\') for i in m.group(3).split(',')] if m.group(3) else []

        # Detect abstract/final
        prefix_text = content[max(0, m.start() - 30):m.start()]
        is_abstract = bool(re.search(r'\babstract\b', prefix_text))
        is_final = bool(re.search(r'\bfinal\b', prefix_text))

        # Detect class type from Laravel conventions
        class_category = _classify_php_class(name, extends, content)

        node_id = _make_id(rel_path, line, name)
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "class",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "extends": extends,
            "implements": implements,
            "is_abstract": is_abstract,
            "is_final": is_final,
            "category": class_category,
        })

        if extends:
            edges.append({
                "from": node_id,
                "to": extends,
                "type": "extends"
            })
        for iface in implements:
            edges.append({
                "from": node_id,
                "to": iface,
                "type": "implements"
            })

        # Extract methods and properties from the class body
        class_body = _extract_block(content, m.end() - 1)
        if class_body:
            _parse_class_members(class_body, rel_path, line, name, node_id, namespace, nodes, edges)

    # ─── Enum declarations (PHP 8.1+) ───────────────────────
    enum_pattern = re.compile(
        r'(?:^|\n)\s*enum\s+(\w+)'
        r'(?:\s*:\s*(\w+))?'    # Backed enum type (int|string)
        r'(?:\s+implements\s+([\w\\,\s]+))?'
        r'\s*\{',
        re.MULTILINE
    )
    for m in enum_pattern.finditer(content):
        name = m.group(1)
        line = _line_of(content, m.start())
        backing_type = m.group(2) or None
        implements = [i.strip().strip('\\') for i in m.group(3).split(',')] if m.group(3) else []

        node_id = _make_id(rel_path, line, name)
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "enum",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "backing_type": backing_type,
            "implements": implements,
        })

    # ─── Standalone functions (not in classes) ──────────────
    # We only parse top-level functions here; class methods are handled above
    func_pattern = re.compile(
        r'(?:^|\n)\s*function\s+(\w+)\s*\(',
        re.MULTILINE
    )
    # Track which line ranges belong to classes to avoid double-counting methods
    class_ranges = _get_class_ranges(content)

    for m in func_pattern.finditer(content):
        name = m.group(1)
        line = _line_of(content, m.start())

        # Skip if inside a class (methods are handled by _parse_class_members)
        if _is_in_range(line, class_ranges):
            continue

        # Skip closures assigned to variables: $fn = function() use (...)
        # These have no name; the regex only matches named functions
        node_id = _make_id(rel_path, line, name)
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "function",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
        })

        # Detect function calls within the function body
        func_body = _extract_block(content, content.index('{', m.start()) if '{' in content[m.start():m.start()+200] else m.start())
        if func_body:
            _parse_function_calls(func_body, rel_path, line, name, node_id, nodes, edges)

    # ─── Laravel-specific patterns ──────────────────────────
    laravel_info = _detect_laravel_patterns(content, rel_path)

    return {
        "nodes": nodes,
        "edges": edges,
        "namespace": namespace,
        "uses": uses,
        "laravel": laravel_info if laravel_info else None,
    }


# ─── Internal Helpers ──────────────────────────────────────

def _line_of(content: str, pos: int) -> int:
    """Return 1-based line number for a position in content."""
    return content[:pos].count('\n') + 1


def _make_id(rel_path: str, line: int, name: str) -> str:
    """Create a unique node ID."""
    return f"{rel_path}:{line}:{name}"


def _extract_block(content: str, brace_pos: int) -> Optional[str]:
    """Extract the content of a braced block starting at brace_pos (which should be '{')."""
    if brace_pos >= len(content) or content[brace_pos] != '{':
        return None

    depth = 0
    start = brace_pos + 1
    i = brace_pos
    while i < len(content):
        ch = content[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return content[start:i]
        i += 1
    # Unclosed brace — return rest of file
    return content[start:]


def _get_class_ranges(content: str) -> List[tuple]:
    """Get line ranges (start, end) of class bodies to avoid double-counting methods."""
    ranges = []
    class_pattern = re.compile(r'(?:^|\n)\s*(?:abstract\s+|final\s+)*class\s+\w+', re.MULTILINE)
    for m in class_pattern.finditer(content):
        start_line = _line_of(content, m.start())
        brace_pos = content.find('{', m.start())
        if brace_pos >= 0:
            body = _extract_block(content, brace_pos)
            if body:
                end_line = start_line + body.count('\n') + 1
                ranges.append((start_line, end_line))
    return ranges


def _is_in_range(line: int, ranges: List[tuple]) -> bool:
    """Check if a line falls within any of the given ranges."""
    for start, end in ranges:
        if start <= line <= end:
            return True
    return False


def _parse_class_members(body: str, rel_path: str, class_line: int,
                         class_name: str, class_node_id: str,
                         namespace: str,
                         nodes: List[Dict], edges: List[Dict]) -> None:
    """Parse methods and properties from a class body string."""
    # ─── Methods ────────────────────────────────────
    method_pattern = re.compile(
        r'(?:public|protected|private|static)\s+'
        r'(?:static\s+)?'
        r'function\s+(\w+)\s*\(',
        re.MULTILINE
    )
    for m in method_pattern.finditer(body):
        name = m.group(1)
        # Calculate line in the original file
        line_in_body = body[:m.start()].count('\n') + 1
        line = class_line + line_in_body

        # Determine visibility
        prefix = body[max(0, m.start() - 40):m.start()]
        visibility = "public"
        if re.search(r'\bprivate\b', prefix):
            visibility = "private"
        elif re.search(r'\bprotected\b', prefix):
            visibility = "protected"
        is_static = bool(re.search(r'\bstatic\b', prefix))

        node_id = _make_id(rel_path, line, f"{class_name}::{name}")
        nodes.append({
            "id": node_id,
            "name": name,
            "fn": name,
            "type": "method",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "class": class_name,
            "visibility": visibility,
            "is_static": is_static,
        })

        edges.append({
            "from": class_node_id,
            "to": node_id,
            "type": "has_method"
        })

        # Detect method calls within the method body
        method_body_start = body.find('{', m.start())
        if method_body_start >= 0:
            method_body = _extract_block(body, method_body_start)
            if method_body:
                _parse_method_calls(method_body, rel_path, line, name, node_id,
                                    class_name, namespace, nodes, edges)

    # ─── Properties ────────────────────────────────
    prop_pattern = re.compile(
        r'(?:public|protected|private)\s+'
        r'(?:static\s+)?'
        r'\$(\w+)',
        re.MULTILINE
    )
    for m in prop_pattern.finditer(body):
        # Skip if this is inside a method (variable, not property)
        # Simple heuristic: check if it's at the start of a line (properties usually are)
        line_start = body.rfind('\n', 0, m.start()) + 1
        line_prefix = body[line_start:m.start()].strip()
        # Properties have visibility keyword at line start; method variables don't
        if not re.match(r'^(public|protected|private|var)', line_prefix):
            continue

        prop_name = m.group(1)
        line_in_body = body[:m.start()].count('\n') + 1
        line = class_line + line_in_body

        prefix = body[max(0, m.start() - 40):m.start()]
        visibility = "public"
        if re.search(r'\bprivate\b', prefix):
            visibility = "private"
        elif re.search(r'\bprotected\b', prefix):
            visibility = "protected"
        is_static = bool(re.search(r'\bstatic\b', prefix))

        nodes.append({
            "id": _make_id(rel_path, line, f"{class_name}::${prop_name}"),
            "name": f"${prop_name}",
            "fn": prop_name,
            "type": "property",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "class": class_name,
            "visibility": visibility,
            "is_static": is_static,
        })

    # ─── Class constants ──────────────────────────
    const_pattern = re.compile(r'const\s+(\w+)\s*=', re.MULTILINE)
    for m in const_pattern.finditer(body):
        name = m.group(1)
        line_in_body = body[:m.start()].count('\n') + 1
        line = class_line + line_in_body

        nodes.append({
            "id": _make_id(rel_path, line, f"{class_name}::{name}"),
            "name": name,
            "fn": name,
            "type": "constant",
            "file": rel_path,
            "line": line,
            "namespace": namespace,
            "class": class_name,
        })

    # ─── Trait use statements ──────────────────────
    trait_use_pattern = re.compile(r'use\s+([\w\\]+(?:\s*,\s*[\w\\]+)*)\s*;')
    for m in trait_use_pattern.finditer(body):
        # Distinguish from closure use() — trait use is at statement level
        prev_char = body[max(0, m.start()-1):m.start()].strip()
        if prev_char == ')':
            continue  # This is a closure use(), not a trait use

        traits = [t.strip().strip('\\') for t in m.group(1).split(',')]
        for trait_name in traits:
            if trait_name[0].isupper():  # Trait names are typically PascalCase
                line_in_body = body[:m.start()].count('\n') + 1
                line = class_line + line_in_body
                edges.append({
                    "from": class_node_id,
                    "to": trait_name,
                    "type": "uses_trait"
                })


def _parse_function_calls(body: str, rel_path: str, func_line: int,
                          func_name: str, func_node_id: str,
                          nodes: List[Dict], edges: List[Dict]) -> None:
    """Detect function/method calls within a function body."""
    # Match: function_name(args) and $obj->method(args) and Class::method(args)
    call_pattern = re.compile(
        r'(?:'
        r'(\$\w+)->(\w+)'          # $obj->method()
        r'|'
        r'([\w\\]+)::(\w+)'        # Class::staticMethod()
        r'|'
        r'\b(\w+)\s*\('            # function_name()
        r')',
    )
    for m in call_pattern.finditer(body):
        if m.group(1) and m.group(2):
            # Instance method call: $obj->method()
            target = m.group(2)
            if target in ('if', 'else', 'while', 'for', 'foreach', 'switch',
                          'return', 'new', 'throw', 'catch', 'try', 'echo',
                          'print', 'isset', 'unset', 'empty', 'list', 'array'):
                continue
            edges.append({
                "from": func_node_id,
                "to": f"->{target}",
                "type": "call",
                "call_type": "instance_method",
            })
        elif m.group(3) and m.group(4):
            # Static method call: Class::method()
            edges.append({
                "from": func_node_id,
                "to": f"{m.group(3)}::{m.group(4)}",
                "type": "call",
                "call_type": "static_method",
            })
        elif m.group(5):
            # Plain function call
            target = m.group(5)
            # Skip control structures and language constructs
            if target in ('if', 'else', 'elseif', 'while', 'for', 'foreach',
                          'switch', 'case', 'return', 'new', 'throw', 'catch',
                          'try', 'echo', 'print', 'isset', 'unset', 'empty',
                          'list', 'array', 'function', 'class', 'include',
                          'require', 'include_once', 'require_once',
                          'define', 'defined', 'var_dump', 'dd', 'dump'):
                continue
            edges.append({
                "from": func_node_id,
                "to": target,
                "type": "call",
                "call_type": "function",
            })


def _parse_method_calls(body: str, rel_path: str, method_line: int,
                        method_name: str, method_node_id: str,
                        class_name: str, namespace: str,
                        nodes: List[Dict], edges: List[Dict]) -> None:
    """Detect function/method calls within a method body."""
    _parse_function_calls(body, rel_path, method_line, method_name, method_node_id, nodes, edges)


def _classify_php_class(name: str, extends: Optional[str], content: str) -> str:
    """Classify a PHP class based on naming conventions and inheritance."""
    # Laravel conventions
    if extends and 'Controller' in (extends or ''):
        return 'controller'
    if extends and 'Model' in (extends or ''):
        return 'model'
    if extends and 'Migration' in (extends or ''):
        return 'migration'
    if extends and 'Command' in (extends or ''):
        return 'command'
    if extends and 'Middleware' in (extends or ''):
        return 'middleware'
    if extends and 'Provider' in (extends or ''):
        return 'service_provider'
    if extends and 'Request' in (extends or ''):
        return 'form_request'
    if extends and 'Exception' in (extends or ''):
        return 'exception'

    # Name-based classification
    if name.endswith('Controller'):
        return 'controller'
    if name.endswith('Model') or name in ('User', 'Server', 'Node', 'Location', 'Allocation', 'Database'):
        return 'model'
    if name.endswith('Middleware'):
        return 'middleware'
    if name.endswith('ServiceProvider') or name.endswith('Provider'):
        return 'service_provider'
    if name.endswith('Request'):
        return 'form_request'
    if name.endswith('Policy'):
        return 'policy'
    if name.endswith('Observer'):
        return 'observer'
    if name.endswith('Listener'):
        return 'listener'
    if name.endswith('Event'):
        return 'event'
    if name.endswith('Job'):
        return 'job'
    if name.endswith('Command'):
        return 'command'
    if name.endswith('Repository'):
        return 'repository'
    if name.endswith('Service'):
        return 'service'
    if name.endswith('Migration') or name.startswith('Create') or name.startswith('Add') or name.startswith('Drop'):
        return 'migration'
    if name.endswith('Seeder'):
        return 'seeder'
    if name.endswith('Factory'):
        return 'factory'

    return 'class'


def _detect_laravel_patterns(content: str, rel_path: str) -> Optional[Dict[str, Any]]:
    """Detect Laravel-specific patterns in PHP source code."""
    info: Dict[str, Any] = {}

    # Route definitions (in route files)
    routes = []
    route_patterns = [
        (r"Route::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)['\"]", "route_definition"),
        (r"Route::(resource)\s*\(\s*['\"]([^'\"]+)['\"]", "resource_route"),
        (r"Route::(apiResource)\s*\(\s*['\"]([^'\"]+)['\"]", "api_resource_route"),
        (r"Route::(group)\s*\(\s*\[", "route_group"),
        (r"Route::(middleware)\s*\(\s*['\"]([^'\"]+)['\"]", "middleware_route"),
    ]
    for pattern, route_type in route_patterns:
        for m in re.finditer(pattern, content):
            if route_type in ("route_definition",):
                routes.append({
                    "method": m.group(1).upper(),
                    "path": m.group(2),
                    "type": route_type,
                })
            elif route_type in ("resource_route", "api_resource_route"):
                routes.append({
                    "method": "RESOURCE",
                    "path": m.group(2),
                    "type": route_type,
                })
            elif route_type == "middleware_route":
                routes.append({
                    "method": "GROUP",
                    "path": m.group(2),
                    "type": "middleware",
                })
    if routes:
        info["routes"] = routes

    # Middleware registrations
    middlewares = []
    for m in re.finditer(r"->middleware\s*\(\s*['\"]([\w.]+)['\"]", content):
        middlewares.append(m.group(1))
    for m in re.finditer(r"->withoutMiddleware\s*\(\s*['\"]([\w.]+)['\"]", content):
        middlewares.append(f"!{m.group(1)}")
    if middlewares:
        info["middlewares"] = middlewares

    # Eloquent model patterns
    eloquent_info = {}
    # $fillable, $guarded, $hidden, $casts
    for attr in ('fillable', 'guarded', 'hidden', 'casts', 'appends'):
        attr_match = re.search(rf'\${attr}\s*=\s*\[([^\]]*)\]', content)
        if attr_match:
            items = re.findall(r"['\"](\w+)['\"]", attr_match.group(1))
            eloquent_info[attr] = items

    # Table name override
    table_match = re.search(r'\$table\s*=\s*[\'"](\w+)[\'"]', content)
    if table_match:
        eloquent_info["table"] = table_match.group(1)

    # Relationships
    relationships = []
    rel_patterns = [
        (r'->(hasOne|hasMany|belongsTo|belongsToMany|morphOne|morphMany|morphTo|morphToMany|morphedByMany)\s*\(\s*([\w\\]+)::class', 'eloquent'),
        (r'->(hasOneThrough|hasManyThrough)\s*\(\s*([\w\\]+)::class', 'eloquent_through'),
    ]
    for pattern, rel_type in rel_patterns:
        for m in re.finditer(pattern, content):
            relationships.append({
                "type": m.group(1),
                "related": m.group(2).rsplit('\\', 1)[-1],
            })
    if relationships:
        eloquent_info["relationships"] = relationships
    if eloquent_info:
        info["eloquent"] = eloquent_info

    # Event listeners
    events = []
    for m in re.finditer(r"Event::listen\s*\(\s*['\"]([\w.]+)['\"]", content):
        events.append(m.group(1))
    for m in re.finditer(r"(?:protected|public)\s+\$listen\s*=\s*\[([^\]]+)\]", content, re.DOTALL):
        for em in re.finditer(r"['\"]([\w.]+)['\"]", m.group(1)):
            events.append(em.group(1))
    if events:
        info["events"] = events

    # Artisan commands
    commands = []
    for m in re.finditer(r"Artisan::command\s*\(\s*['\"]([^'\"]+)['\"]", content):
        commands.append(m.group(1))
    cmd_name = re.search(r"protected\s+\$signature\s*=\s*['\"]([^'\"]+)['\"]", content)
    if cmd_name:
        commands.append(cmd_name.group(1))
    if commands:
        info["artisan_commands"] = commands

    # Blade directives used in PHP (rare, but @include, @yield in service providers)
    # Not common, skip for now

    return info if info else None

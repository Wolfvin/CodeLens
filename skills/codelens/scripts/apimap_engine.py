"""
API Map Engine for CodeLens — v3
Maps REST/GraphQL/gRPC route → handler → middleware for web applications.
Answers: "What endpoints exist? What handles POST /users?"

Framework Detection & Route Extraction:
 1. Express   — app.get/post/put/delete/patch, Router, Route
 2. Fastify   — fastify.get/post, plugin routes
 3. Koa       — router.get/post, koa-router
 4. Hono      — hono.get/post
 5. Next.js   — pages/api/* or app/api/*/route.ts
 6. Nuxt      — server/api/* handlers
 7. Django    — urlpatterns, path(), re_path(), @api_view
 8. Flask     — @app.route, @blueprint.route
 9. FastAPI   — @app.get/post, @router.get/post
10. GraphQL   — type Query, type Mutation, resolvers
11. gRPC      — service definitions in .proto files
12. tRPC      — router definitions, procedure chains
13. oRPC      — procedure chains, router objects
14. SvelteKit — file-based routes (+page, +server, +layout, +error)
15. Go stdlib — net/http: HandleFunc, Handle
16. Gin      — r.GET/POST/PUT/DELETE/PATCH
17. Echo     — e.GET/POST/PUT/DELETE/PATCH
18. Chi      — r.Get/Post/Put/Delete, r.Route
19. Fiber    — app.Get/Post/Put/Delete
20. httprouter — router.GET/POST, router.Handle

Per-route extraction: method, path, handler_name, file, line,
                      middleware_chain, request_type, response_type

Additional detection: middleware stacks, route groups/prefixes,
                      auth-protected vs public, deprecated routes.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".proto",
    ".graphql", ".gql", ".php",
    ".rb", ".ex", ".exs",
    ".go",
}

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

# Valid HTTP methods in uppercase (for validation of extracted method names)
VALID_HTTP_METHODS_UPPER = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "ALL"}

# Non-router objects whose .get/.post/.delete etc. calls should NOT be treated as routes
NON_ROUTER_OBJECTS = {
    "console", "Promise", "Array", "Object", "Map", "Set", "JSON", "Math",
    "res", "req", "ctx", "request", "response", "result", "data",
    "props", "state", "config", "options", "headers",
    "localStorage", "sessionStorage", "document", "window",
    "cache", "store", "db", "query", "client",
}

# Known middleware identifiers
AUTH_MIDDLEWARE_PATTERNS = {
    "authenticate", "auth", "jwt", "passport", "requireAuth",
    "isAuthenticated", "verifyToken", "checkAuth", "ensureAuthenticated",
    "login_required", "permission_required", "auth_required",
}

CORS_MIDDLEWARE_PATTERNS = {
    "cors", "CORS", "corsMiddleware", "handleCORS",
}

RATE_LIMIT_PATTERNS = {
    "rateLimit", "rateLimiter", "rate-limit", "throttle",
    "RateLimiter", "apiLimiter",
}

VALIDATION_PATTERNS = {
    "validate", "validation", "validator", "schema", "joi",
    "zod", "yup", "celebrate", "checkSchema",
}


def map_api_routes(
    workspace: str,
    method: Optional[str] = None,
    path_filter: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Map all API routes in the workspace, detecting framework and extracting
    route → handler → middleware chains.

    Args:
        workspace: Absolute path to workspace
        method: Optional HTTP method filter (GET, POST, etc.)
        path_filter: Optional path prefix filter (e.g., '/api/users')
        config: CodeLens config dict

    Returns:
        Dict with frameworks_detected, stats, routes, route_groups,
        middleware_map, recommendations
    """
    workspace = os.path.abspath(workspace)

    routes: List[Dict[str, Any]] = []
    frameworks_detected: Set[str] = set()
    middleware_map: Dict[str, List[Dict]] = defaultdict(list)
    route_groups: List[Dict[str, Any]] = []
    files_scanned = 0

    # Global middleware collectors
    global_middleware: List[Dict] = []
    auth_protected_routes: Set[str] = set()

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # ─── Express / Koa / Hono / Fastify ──────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                js_routes = _extract_js_routes(content, rel_path, frameworks_detected)
                routes.extend(js_routes)

                # Detect global middleware
                mw = _extract_js_middleware(content, rel_path)
                global_middleware.extend(mw)

            # ─── Next.js API Routes ───────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                next_routes = _extract_nextjs_routes(content, rel_path, root, workspace)
                if next_routes:
                    frameworks_detected.add("nextjs")
                    routes.extend(next_routes)

            # ─── Nuxt Server Routes ───────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                nuxt_routes = _extract_nuxt_routes(content, rel_path, root, workspace)
                if nuxt_routes:
                    frameworks_detected.add("nuxt")
                    routes.extend(nuxt_routes)

            # ─── Python: Flask / FastAPI / Django ─────────────
            elif ext == ".py":
                py_routes = _extract_python_routes(content, rel_path, frameworks_detected)
                routes.extend(py_routes)

                py_mw = _extract_python_middleware(content, rel_path)
                global_middleware.extend(py_mw)

            # ─── PHP: Laravel / Symfony / Slim ─────────────────
            elif ext == ".php":
                php_routes = _extract_php_routes(content, rel_path, frameworks_detected)
                routes.extend(php_routes)

                php_mw = _extract_php_middleware(content, rel_path)
                global_middleware.extend(php_mw)

            # ─── GraphQL ──────────────────────────────────────
            elif ext in {".graphql", ".gql"}:
                gql_routes = _extract_graphql_schema(content, rel_path)
                if gql_routes:
                    frameworks_detected.add("graphql")
                    routes.extend(gql_routes)

            # Also detect GraphQL in JS/TS files
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                gql_code_routes = _extract_graphql_code(content, rel_path)
                if gql_code_routes:
                    frameworks_detected.add("graphql")
                    routes.extend(gql_code_routes)

            # Also detect GraphQL in Python files
            if ext == ".py":
                gql_py_routes = _extract_graphql_python(content, rel_path)
                if gql_py_routes:
                    frameworks_detected.add("graphql")
                    routes.extend(gql_py_routes)

            # ─── gRPC (.proto) ────────────────────────────────
            elif ext == ".proto":
                grpc_routes = _extract_grpc_services(content, rel_path)
                if grpc_routes:
                    frameworks_detected.add("grpc")
                    routes.extend(grpc_routes)

            # ─── tRPC ─────────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                trpc_routes = _extract_trpc_routes(content, rel_path)
                if trpc_routes:
                    frameworks_detected.add("trpc")
                    routes.extend(trpc_routes)

            # ─── oRPC ─────────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                orpc_routes = _extract_orpc_routes(content, rel_path)
                if orpc_routes:
                    frameworks_detected.add("orpc")
                    routes.extend(orpc_routes)

            # ─── Tauri IPC (frontend invoke calls) ────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".svelte", ".vue"}:
                tauri_routes = _extract_tauri_ipc_routes(content, rel_path)
                if tauri_routes:
                    frameworks_detected.add("tauri")
                    routes.extend(tauri_routes)

            # ─── Tauri IPC (backend Rust commands) ────────────
            if ext == ".rs":
                tauri_cmd_routes = _extract_tauri_rust_commands(content, rel_path)
                if tauri_cmd_routes:
                    frameworks_detected.add("tauri")
                    routes.extend(tauri_cmd_routes)

                # v5.8: Rust HTTP handler detection (actix-web, axum, warp, rocket)
                rust_http_routes = _extract_rust_http_routes(content, rel_path)
                if rust_http_routes:
                    routes.extend(rust_http_routes)
                    # Track which Rust framework was detected
                    for r in rust_http_routes:
                        fw = r.get("framework", "")
                        if fw:
                            frameworks_detected.add(fw)

            # ─── Ruby: Rails routes ─────────────────────────────
            elif ext == ".rb":
                rails_routes = _extract_rails_routes(content, rel_path, frameworks_detected)
                routes.extend(rails_routes)

            # ─── Elixir: Phoenix routes ─────────────────────────
            elif ext in (".ex", ".exs"):
                phoenix_routes = _extract_phoenix_routes(content, rel_path, frameworks_detected)
                routes.extend(phoenix_routes)

            # ─── Go: net/http / Gin / Echo / Chi / Fiber / httprouter ──
            elif ext == ".go":
                go_routes = _extract_go_routes(content, rel_path, frameworks_detected)
                routes.extend(go_routes)

    # ─── Go framework detection from go.mod ───────────────────
    _detect_go_frameworks(workspace, frameworks_detected)

    # ─── SvelteKit file-based routes ─────────────────────────
    sveltekit_routes = _detect_sveltekit_routes(workspace, config)
    if sveltekit_routes:
        frameworks_detected.add("sveltekit")
        routes.extend(sveltekit_routes)

    # ─── Post-processing ──────────────────────────────────────

    # Attach middleware to routes
    for mw in global_middleware:
        scope = mw.get("scope", "global")
        if scope == "global":
            for route in routes:
                route.setdefault("middleware_chain", []).append({
                    "name": mw["name"],
                    "type": mw.get("type", "unknown"),
                    "file": mw["file"],
                    "line": mw["line"],
                })

    # Build middleware map
    for route in routes:
        for mw in route.get("middleware_chain", []):
            middleware_map[mw["name"]].append({
                "route": f"{route['method']} {route['path']}",
                "type": mw.get("type", "unknown"),
            })

    # Detect auth-protected vs public
    for route in routes:
        has_auth = any(
            mw.get("type") == "auth"
            for mw in route.get("middleware_chain", [])
        )
        route["auth_protected"] = has_auth
        if has_auth:
            auth_protected_routes.add(f"{route['method']} {route['path']}")

    # Build route groups by path prefix
    route_groups = _build_route_groups(routes)

    # Mark deprecated routes
    for route in routes:
        route["deprecated"] = _is_deprecated_route(route)

    # Apply filters
    if method:
        method_upper = method.upper()
        routes = [r for r in routes if r["method"].upper() == method_upper]

    if path_filter:
        routes = [r for r in routes if r["path"].startswith(path_filter)]

    # Stats
    by_method: Dict[str, int] = defaultdict(int)
    for r in routes:
        by_method[r["method"].upper()] += 1

    auth_count = sum(1 for r in routes if r.get("auth_protected"))
    public_count = len(routes) - auth_count

    # Recommendations
    recommendations = _generate_recommendations(
        routes, frameworks_detected, auth_protected_routes
    )

    return {
        "status": "ok",
        "workspace": workspace,
        "frameworks_detected": sorted(frameworks_detected),
        "stats": {
            "total_routes": len(routes),
            "by_method": dict(by_method),
            "auth_protected": auth_count,
            "public": public_count,
            "files_scanned": files_scanned,
        },
        "routes": routes,
        "route_groups": route_groups,
        "middleware_map": dict(middleware_map),
        "recommendations": recommendations,
    }


# ─── JS Route Extraction ───────────────────────────────────────

def _extract_js_routes(
    content: str, rel_path: str, frameworks: Set[str]
) -> List[Dict[str, Any]]:
    """Extract routes from Express / Fastify / Koa / Hono JS/TS files."""
    routes = []
    lines = content.split('\n')

    # Detect which framework by import/require patterns
    is_express = bool(re.search(r'(?:require|import).*[\'\"]express[\'\"]', content))
    is_fastify = bool(re.search(r'(?:require|import).*[\'\"]fastify[\'\"]', content))
    is_koa = bool(re.search(r'(?:require|import).*[\'\"]koa-router[\'\"]|ko[\'\"]koa[\'\"]', content))
    is_hono = bool(re.search(r'(?:require|import).*[\'\"]hono[\'\"]', content))

    if is_express:
        frameworks.add("express")
    if is_fastify:
        frameworks.add("fastify")
    if is_koa:
        frameworks.add("koa")
    if is_hono:
        frameworks.add("hono")

    # Track current router variable names and prefixes
    router_vars: Dict[str, str] = {}  # var_name → prefix

    # Detect Router() assignments: const router = Router({ prefix: '/api' })
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*(?:new\s+)?(?:Router|router)\s*\(([^)]*)\)',
        content
    ):
        var_name = m.group(1)
        args = m.group(2)
        prefix_match = re.search(r'prefix\s*:\s*[\'"]([^\'"]+)[\'"]', args)
        prefix = prefix_match.group(1) if prefix_match else ""
        router_vars[var_name] = prefix

    # Detect app.route('/path') chains
    for m in re.finditer(
        r'(?:app|router|server|fastify|hono)\s*\.\s*route\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        content
    ):
        base_path = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        # Look for chained methods after this
        chain_start = m.end()
        chain_text = content[chain_start:chain_start + 500]
        for cm in re.finditer(r'\.(get|post|put|delete|patch)\s*\(', chain_text):
            method = cm.group(1).upper()
            routes.append({
                "method": method,
                "path": base_path,
                "handler_name": _infer_handler_name(chain_text, cm.start()),
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": _detect_js_framework(is_express, is_fastify, is_koa, is_hono),
            })

    # Direct method calls: app.get('/path', ...), router.post('/path', ...)
    for m in re.finditer(
        r'(\w+)\s*\.\s*(get|post|put|delete|patch|head|options)\s*\(\s*[\'"`]([^\'"`]*)[\'"`]',
        content
    ):
        obj_name = m.group(1)
        http_method = m.group(2).upper()
        route_path = m.group(3)

        # Skip non-route method calls
        if obj_name in NON_ROUTER_OBJECTS:
            continue
        if http_method.lower() not in HTTP_METHODS:
            continue

        # Skip paths that don't look like routes (e.g., cookie names, header names)
        if not route_path.startswith('/'):
            continue

        line_num = content[:m.start()].count('\n') + 1

        # Apply router prefix if available
        prefix = router_vars.get(obj_name, "")
        full_path = _normalize_path(prefix + route_path)

        # Extract middleware from arguments
        mw_chain = _extract_inline_middleware(content, m.end(), rel_path, line_num)

        # Extract handler name
        handler_name = _infer_handler_name_from_args(content, m.end())

        # Detect request/response types from nearby code
        req_type, resp_type = _detect_request_response_types(content, m.start())

        routes.append({
            "method": http_method,
            "path": full_path,
            "handler_name": handler_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": mw_chain,
            "request_type": req_type,
            "response_type": resp_type,
            "framework": _detect_js_framework(is_express, is_fastify, is_koa, is_hono),
        })

    return routes


def _detect_js_framework(is_express, is_fastify, is_koa, is_hono) -> str:
    """Return the detected JS framework name."""
    if is_fastify:
        return "fastify"
    if is_hono:
        return "hono"
    if is_koa:
        return "koa"
    if is_express:
        return "express"
    return "unknown"


def _extract_inline_middleware(
    content: str, start_pos: int, rel_path: str, line_num: int
) -> List[Dict[str, Any]]:
    """Extract middleware from route handler arguments between path and final handler."""
    middleware = []

    # Find the arguments section
    paren_start = content.find('(', start_pos - 1)
    if paren_start < 0:
        return middleware

    # Find matching closing paren
    depth = 1
    pos = paren_start + 1
    while pos < len(content) and depth > 0:
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
        pos += 1

    args_section = content[paren_start + 1:pos - 1]

    # Split by comma at depth 0
    args = _split_args(args_section)

    # All args except the path (first) and the handler (last) are middleware
    if len(args) > 2:
        for arg in args[1:-1]:
            arg = arg.strip()
            if not arg:
                continue
            mw_name = arg.strip()
            # Remove wrapping like cors(), auth()
            bare_name = re.sub(r'\(.*\)', '', mw_name).strip()

            mw_type = _classify_middleware(bare_name)
            middleware.append({
                "name": bare_name or mw_name,
                "type": mw_type,
                "file": rel_path,
                "line": line_num,
            })

    return middleware


def _split_args(args_str: str) -> List[str]:
    """Split function arguments at depth 0 commas."""
    args = []
    depth = 0
    current = []
    for ch in args_str:
        if ch in '([{':
            depth += 1
            current.append(ch)
        elif ch in ')]}':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        args.append(''.join(current))
    return args


def _classify_middleware(name: str) -> str:
    """Classify middleware by its name patterns."""
    lower = name.lower()
    for pattern in AUTH_MIDDLEWARE_PATTERNS:
        if pattern.lower() in lower:
            return "auth"
    for pattern in CORS_MIDDLEWARE_PATTERNS:
        if pattern.lower() in lower:
            return "cors"
    for pattern in RATE_LIMIT_PATTERNS:
        if pattern.lower() in lower:
            return "rate_limit"
    for pattern in VALIDATION_PATTERNS:
        if pattern.lower() in lower:
            return "validation"
    return "custom"


def _infer_handler_name(content: str, offset: int) -> str:
    """Try to infer the handler function name from code near offset."""
    snippet = content[offset:offset + 300]
    # Look for named function passed as handler
    m = re.search(r'(?:,\s*(\w+)\s*(?:,\s*|\))|,\s*(?:async\s+)?function\s+(\w+))', snippet)
    if m:
        return m.group(1) or m.group(2) or "anonymous"
    return "anonymous"


def _infer_handler_name_from_args(content: str, start_pos: int) -> str:
    """Infer handler name from the last argument of a route call."""
    paren_start = content.find('(', start_pos - 1)
    if paren_start < 0:
        return "anonymous"

    depth = 1
    pos = paren_start + 1
    while pos < len(content) and depth > 0:
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
        pos += 1

    args_section = content[paren_start + 1:pos - 1]
    args = _split_args(args_section)

    if args:
        last_arg = args[-1].strip()
        # Extract name from arrow function or named function
        m = re.search(r'(?:async\s+)?(\w+)\s*=>', last_arg)
        if m:
            return m.group(1) + "_handler"
        m = re.search(r'function\s+(\w+)', last_arg)
        if m:
            return m.group(1)
        # Just a variable reference
        if re.match(r'^\w+$', last_arg):
            return last_arg

    return "anonymous"


def _detect_request_response_types(
    content: str, offset: int
) -> tuple:
    """Heuristically detect request/response type annotations near a route."""
    req_type = None
    resp_type = None

    # Look for TypeScript generic type params like app.get<ReqType, ResType>
    nearby = content[max(0, offset - 20):offset + 200]
    m = re.search(r'<(\w+),\s*(\w+)>', nearby)
    if m:
        req_type = m.group(1)
        resp_type = m.group(2)

    # Look for FastAPI-style response_model or similar
    m = re.search(r'response_model\s*=\s*(\w+)', nearby)
    if m:
        resp_type = m.group(1)

    # Look for : Response annotations
    m = re.search(r'response\s*:\s*(\w+)', nearby, re.IGNORECASE)
    if m and not resp_type:
        resp_type = m.group(1)

    return req_type, resp_type


# ─── JS Middleware Extraction ──────────────────────────────────

def _extract_js_middleware(content: str, rel_path: str) -> List[Dict]:
    """Extract global/app-level middleware from JS files."""
    middleware = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # app.use(middleware) patterns
        m = re.match(
            r'(?:app|server|fastify|hono)\s*\.\s*use\s*\(\s*(\w+)',
            stripped
        )
        if m:
            mw_name = m.group(1)
            mw_type = _classify_middleware(mw_name)
            middleware.append({
                "name": mw_name,
                "type": mw_type,
                "scope": "global",
                "file": rel_path,
                "line": i + 1,
            })

        # app.use('/path', middleware) — route-scoped middleware
        m = re.match(
            r'(?:app|server|fastify|hono)\s*\.\s*use\s*\(\s*[\'"`]([^\'"`]+)[\'"`]\s*,\s*(\w+)',
            stripped
        )
        if m:
            mw_path = m.group(1)
            # Only treat as route-scoped middleware if the path looks like a real route
            # (starts with /) — filter out cookie names, variable names, etc.
            if not mw_path.startswith('/'):
                # Might be a config string (e.g., cookie secret), not a route path
                # Treat as global middleware instead
                mw_name = m.group(2)
                mw_type = _classify_middleware(mw_name)
                middleware.append({
                    "name": mw_name,
                    "type": mw_type,
                    "scope": "global",
                    "file": rel_path,
                    "line": i + 1,
                })
            else:
                mw_name = m.group(2)
                mw_type = _classify_middleware(mw_name)
                middleware.append({
                    "name": mw_name,
                    "type": mw_type,
                    "scope": f"path:{mw_path}",
                    "file": rel_path,
                    "line": i + 1,
                })

    return middleware


# ─── Next.js Routes ────────────────────────────────────────────

def _extract_nextjs_routes(
    content: str, rel_path: str, root: str, workspace: str
) -> List[Dict[str, Any]]:
    """Extract Next.js API routes from pages/api/* or app/api/*/route.ts."""
    routes = []

    # pages/api/* pattern
    if 'pages/api/' in rel_path or 'pages\\api\\' in rel_path:
        # Convert file path to API route
        # In monorepos, the path might be "apps/readest-app/src/pages/api/..."
        # We need to find "pages/api" anywhere in the path, not just at the start
        api_path = re.sub(r'^.*?pages[/\\]api', '/api', rel_path)
        api_path = re.sub(r'\.(js|ts|mjs|cjs)$', '', api_path)
        api_path = api_path.replace('\\', '/')
        # Handle [param] → :param
        api_path = re.sub(r'\[([^\]]+)\]', r':\1', api_path)
        # Handle [...param] → :param*
        api_path = re.sub(r':\.\.\.(\w+)', r':\1*', api_path)
        # /index → /
        api_path = re.sub(r'/index$', '', api_path)

        # Default export = handler for all methods
        if re.search(r'export\s+default\s+', content):
            # Detect specific method handlers
            for method_match in re.finditer(
                r'(?:req\.method\s*===?\s*[\'"](\w+)[\'"]|case\s+[\'"](\w+)[\'"])',
                content
            ):
                http_method = (method_match.group(1) or method_match.group(2)).upper()
                # Validate that this is actually an HTTP method, not a random string
                # (e.g., 'HOUR', 'DAY', 'WEEK' from date-fns switch statements)
                if http_method not in VALID_HTTP_METHODS_UPPER:
                    continue
                line_num = content[:method_match.start()].count('\n') + 1
                routes.append({
                    "method": http_method,
                    "path": _normalize_path(api_path),
                    "handler_name": "default_handler",
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "nextjs",
                })

            if not routes:
                routes.append({
                    "method": "ALL",
                    "path": _normalize_path(api_path),
                    "handler_name": "default_handler",
                    "file": rel_path,
                    "line": 1,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "nextjs",
                })

    # app/api/*/route.ts pattern — exported GET, POST, etc.
    # Supports nested directories like app/api/auth/[...all]/route.ts
    if re.search(r'app[/\\]api[/\\].*[/\\]route\.(ts|js|mjs|cjs)$', rel_path):
        api_path = re.sub(r'^.*?app[/\\]api', '/api', rel_path)
        api_path = re.sub(r'/route\.(ts|js|mjs|cjs)$', '', api_path)
        api_path = api_path.replace('\\', '/')
        api_path = re.sub(r'\[([^\]]+)\]', r':\1', api_path)
        api_path = re.sub(r':\.\.\.(\w+)', r':\1*', api_path)

        # Pattern 1: export async function GET / POST / etc.
        for m in re.finditer(
            r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)',
            content
        ):
            http_method = m.group(1).upper()
            line_num = content[:m.start()].count('\n') + 1
            routes.append({
                "method": http_method,
                "path": _normalize_path(api_path),
                "handler_name": m.group(1),
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "nextjs",
            })

        # Pattern 2: export const { GET, POST } = handler() (destructured exports)
        for m in re.finditer(
            r'export\s+const\s*\{\s*([^\}]+)\}\s*=',
            content
        ):
            destructure_list = m.group(1)
            for method_name in re.findall(
                r'(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b',
                destructure_list
            ):
                http_method = method_name.upper()
                line_num = content[:m.start()].count('\n') + 1
                routes.append({
                    "method": http_method,
                    "path": _normalize_path(api_path),
                    "handler_name": method_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "nextjs",
                })

        # Pattern 3: export const GET = ... / export const POST = ... (individual const exports)
        for m in re.finditer(
            r'export\s+const\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*=',
            content
        ):
            http_method = m.group(1).upper()
            line_num = content[:m.start()].count('\n') + 1
            routes.append({
                "method": http_method,
                "path": _normalize_path(api_path),
                "handler_name": m.group(1),
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "nextjs",
            })

    return routes


# ─── Nuxt Routes ───────────────────────────────────────────────

def _extract_nuxt_routes(
    content: str, rel_path: str, root: str, workspace: str
) -> List[Dict[str, Any]]:
    """Extract Nuxt server/api/* handler routes."""
    routes = []

    if 'server/api/' in rel_path or 'server\\api\\' in rel_path:
        api_path = re.sub(r'^server[/\\]api', '/api', rel_path)
        api_path = re.sub(r'\.(js|ts|mjs|cjs)$', '', api_path)
        api_path = api_path.replace('\\', '/')
        api_path = re.sub(r'\[([^\]]+)\]', r':\1', api_path)

        # Nuxt uses defineEventHandler or export default
        handler_name = "eventHandler"
        m = re.search(r'(?:export\s+default\s+)?defineEventHandler\s*(?:<[^>]+>)?\s*\(', content)
        if m:
            line_num = content[:m.start()].count('\n') + 1
            routes.append({
                "method": "ALL",
                "path": _normalize_path(api_path),
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "nuxt",
            })

        # Nuxt method-specific files: .get.ts, .post.ts, etc.
        method_match = re.search(r'\.(get|post|put|delete|patch)\.(ts|js)$', rel_path)
        if method_match:
            http_method = method_match.group(1).upper()
            api_path = re.sub(r'\.(get|post|put|delete|patch)\.(ts|js)$', '', api_path)
            routes.append({
                "method": http_method,
                "path": _normalize_path(api_path),
                "handler_name": handler_name,
                "file": rel_path,
                "line": 1,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "nuxt",
            })

    return routes


# ─── SvelteKit Routes ─────────────────────────────────────────

def _detect_sveltekit_routes(
    workspace: str, config: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """Detect SvelteKit file-based routes from the src/routes/ directory.

    SvelteKit uses file-system routing:
      +page.svelte        → page route (GET)
      +page.ts            → page load function
      +page.server.ts     → page server-side load / actions
      +server.ts / +server.js → API endpoint (exports GET, POST, etc.)
      +layout.svelte      → layout component
      +layout.ts          → layout load function
      +layout.server.ts   → layout server-side load
      +error.svelte       → error page

    Dynamic segments use [param] syntax, e.g.:
      src/routes/blog/[slug]/+page.svelte → /blog/:slug
    """
    routes: List[Dict[str, Any]] = []
    routes_dir = os.path.join(workspace, "src", "routes")

    # Quick check: SvelteKit must have src/routes/ directory
    if not os.path.isdir(routes_dir):
        return routes

    # Also check for svelte.config.js or vite.config with SvelteKit
    has_sveltekit_config = os.path.isfile(os.path.join(workspace, "svelte.config.js")) \
                        or os.path.isfile(os.path.join(workspace, "svelte.config.ts"))
    # If no svelte.config but src/routes exists with SvelteKit files, still detect

    # SvelteKit special filenames and their route types
    SERVER_FILES = {"+server.ts", "+server.js", "+server.mjs", "+server.cjs"}
    PAGE_FILES = {"+page.svelte", "+page.ts", "+page.js", "+page.server.ts", "+page.server.js"}
    LAYOUT_FILES = {"+layout.svelte", "+layout.ts", "+layout.js", "+layout.server.ts", "+layout.server.js"}
    ERROR_FILES = {"+error.svelte", "+error.ts", "+error.js"}

    all_special_files = SERVER_FILES | PAGE_FILES | LAYOUT_FILES | ERROR_FILES
    found_sveltekit_file = False

    for root, dirs, filenames in os.walk(routes_dir):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

        for filename in filenames:
            if filename not in all_special_files:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Convert directory path to route path
            # e.g. src/routes/api/users/+server.ts → /api/users
            route_dir = os.path.relpath(root, routes_dir)
            if route_dir == '.':
                route_path = '/'
            else:
                route_path = '/' + route_dir.replace(os.sep, '/')

            # Handle SvelteKit dynamic segments: [param] → :param, [...param] → :param*
            route_path = re.sub(r'\[\.\.\.(\w+)\]', r':\1*', route_path)
            route_path = re.sub(r'\[([^\]]+)\]', r':\1', route_path)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                content = ""

            # ─── +server.ts/js — API endpoints with HTTP method exports ───
            if filename in SERVER_FILES:
                found_sveltekit_file = True
                methods_found = []

                # Pattern 1: export async function GET / POST / etc.
                for m in re.finditer(
                    r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)',
                    content
                ):
                    http_method = m.group(1).upper()
                    line_num = content[:m.start()].count('\n') + 1
                    methods_found.append({"method": http_method, "handler": m.group(1), "line": line_num})

                # Pattern 2: export const GET = ... / export const POST = ...
                for m in re.finditer(
                    r'export\s+const\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*=',
                    content
                ):
                    http_method = m.group(1).upper()
                    line_num = content[:m.start()].count('\n') + 1
                    methods_found.append({"method": http_method, "handler": m.group(1), "line": line_num})

                # Pattern 3: export { GET, POST } (re-exports)
                for m in re.finditer(
                    r'export\s+\{\s*([^\}]+)\}\s*',
                    content
                ):
                    for method_name in re.findall(
                        r'\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b',
                        m.group(1)
                    ):
                        http_method = method_name.upper()
                        line_num = content[:m.start()].count('\n') + 1
                        methods_found.append({"method": http_method, "handler": method_name, "line": line_num})

                if methods_found:
                    for mf in methods_found:
                        routes.append({
                            "method": mf["method"],
                            "path": _normalize_path(route_path),
                            "handler_name": mf["handler"],
                            "file": rel_path,
                            "line": mf["line"],
                            "middleware_chain": [],
                            "request_type": None,
                            "response_type": None,
                            "framework": "sveltekit",
                            "type": "api_endpoint",
                        })
                else:
                    # No method exports found — still register as a generic endpoint
                    routes.append({
                        "method": "ALL",
                        "path": _normalize_path(route_path),
                        "handler_name": "+server",
                        "file": rel_path,
                        "line": 1,
                        "middleware_chain": [],
                        "request_type": None,
                        "response_type": None,
                        "framework": "sveltekit",
                        "type": "api_endpoint",
                    })

            # ─── +page.svelte / +page.ts / +page.server.ts — page routes ───
            elif filename in PAGE_FILES:
                found_sveltekit_file = True

                # Determine handler name from content
                handler_name = "+page"
                line_num = 1
                if ".server." in filename:
                    # Look for load function or actions export
                    load_match = re.search(
                        r'export\s+(?:async\s+)?function\s+load\b',
                        content
                    )
                    actions_match = re.search(
                        r'export\s+const\s+actions\s*=',
                        content
                    )
                    if load_match:
                        handler_name = "load"
                        line_num = content[:load_match.start()].count('\n') + 1
                    elif actions_match:
                        handler_name = "actions"
                        line_num = content[:actions_match.start()].count('\n') + 1
                elif filename.endswith(".ts") or filename.endswith(".js"):
                    load_match = re.search(
                        r'export\s+(?:async\s+)?function\s+load\b',
                        content
                    )
                    if load_match:
                        handler_name = "load"
                        line_num = content[:load_match.start()].count('\n') + 1

                # +page.server.ts with actions → also emit POST for form actions
                if ".server." in filename:
                    actions_match = re.search(
                        r'export\s+const\s+actions\s*=',
                        content
                    )
                    if actions_match:
                        actions_line = content[:actions_match.start()].count('\n') + 1
                        # Find named actions (e.g. actions: { create, delete })
                        named_actions = re.findall(
                            r'actions\s*:\s*\{([^}]+)\}',
                            content
                        )
                        action_names = []
                        for block in named_actions:
                            action_names.extend(re.findall(r'(\w+)\s*:', block))

                        # Emit POST for default action
                        routes.append({
                            "method": "POST",
                            "path": _normalize_path(route_path),
                            "handler_name": "actions",
                            "file": rel_path,
                            "line": actions_line,
                            "middleware_chain": [],
                            "request_type": None,
                            "response_type": None,
                            "framework": "sveltekit",
                            "type": "page",
                        })

                        # Emit POST for each named action
                        for action_name in action_names:
                            routes.append({
                                "method": "POST",
                                "path": _normalize_path(route_path),
                                "handler_name": action_name,
                                "file": rel_path,
                                "line": actions_line,
                                "middleware_chain": [],
                                "request_type": None,
                                "response_type": None,
                                "framework": "sveltekit",
                                "type": "page",
                            })

                routes.append({
                    "method": "GET",
                    "path": _normalize_path(route_path),
                    "handler_name": handler_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "sveltekit",
                    "type": "page",
                })

            # ─── +layout.svelte / +layout.ts / +layout.server.ts — layouts ───
            elif filename in LAYOUT_FILES:
                found_sveltekit_file = True

                handler_name = "+layout"
                line_num = 1
                if ".server." in filename:
                    load_match = re.search(
                        r'export\s+(?:async\s+)?function\s+load\b',
                        content
                    )
                    if load_match:
                        handler_name = "load"
                        line_num = content[:load_match.start()].count('\n') + 1
                elif filename.endswith(".ts") or filename.endswith(".js"):
                    load_match = re.search(
                        r'export\s+(?:async\s+)?function\s+load\b',
                        content
                    )
                    if load_match:
                        handler_name = "load"
                        line_num = content[:load_match.start()].count('\n') + 1

                routes.append({
                    "method": "ALL",
                    "path": _normalize_path(route_path),
                    "handler_name": handler_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "sveltekit",
                    "type": "layout",
                })

            # ─── +error.svelte / +error.ts — error pages ───
            elif filename in ERROR_FILES:
                found_sveltekit_file = True

                routes.append({
                    "method": "ALL",
                    "path": _normalize_path(route_path),
                    "handler_name": "+error",
                    "file": rel_path,
                    "line": 1,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "sveltekit",
                    "type": "error",
                })

    # Only return routes if we actually found SvelteKit files
    # (a bare src/routes/ dir without +files is not a SvelteKit project)
    if not found_sveltekit_file:
        return []

    return routes


# ─── Python Routes (Flask / FastAPI / Django) ─────────────────

def _extract_python_routes(
    content: str, rel_path: str, frameworks: Set[str]
) -> List[Dict[str, Any]]:
    """Extract routes from Flask, FastAPI, and Django Python files."""
    routes = []

    is_flask = bool(re.search(r'(?:from\s+flask\s+import|import\s+flask)', content))
    is_fastapi = bool(re.search(r'(?:from\s+fastapi\s+import|import\s+fastapi)', content))
    is_django = bool(re.search(r'(?:from\s+django|import\s+django)', content))

    if is_flask:
        frameworks.add("flask")
    if is_fastapi:
        frameworks.add("fastapi")
    if is_django:
        frameworks.add("django")

    # Flask / FastAPI decorator routes
    if is_flask or is_fastapi:
        fw_name = "fastapi" if is_fastapi else "flask"

        # @app.route('/path', methods=['GET', 'POST'])
        for m in re.finditer(
            r'@(\w+)\s*\.\s*route\s*\(\s*[\'"]([^\'"]+)[\'"]\s*(?:,\s*methods\s*=\s*\[([^\]]*)\])?',
            content
        ):
            obj_name = m.group(1)
            route_path = m.group(2)
            methods_str = m.group(3) or "'GET'"
            line_num = content[:m.start()].count('\n') + 1

            methods = re.findall(r'[\'"](\w+)[\'"]', methods_str)
            if not methods:
                methods = ["GET"]

            # Find handler function name
            handler_name = _find_next_python_function(content, m.end())

            # Extract middleware from decorators before the handler
            mw_chain = _extract_python_decorator_middleware(content, m.start(), rel_path, line_num)

            for method in methods:
                method_upper = method.upper()
                # Validate HTTP method
                if method_upper not in VALID_HTTP_METHODS_UPPER:
                    continue
                routes.append({
                    "method": method_upper,
                    "path": _normalize_path(route_path),
                    "handler_name": handler_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": mw_chain,
                    "request_type": None,
                    "response_type": None,
                    "framework": fw_name,
                })

        # FastAPI method decorators: @app.get('/path'), @router.post('/path')
        if is_fastapi:
            for m in re.finditer(
                r'@(\w+)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]*)[\'"]',
                content
            ):
                obj_name = m.group(1)
                http_method = m.group(2).upper()
                route_path = m.group(3)
                line_num = content[:m.start()].count('\n') + 1

                handler_name = _find_next_python_function(content, m.end())
                mw_chain = _extract_python_decorator_middleware(content, m.start(), rel_path, line_num)

                # Detect response_model
                resp_type = None
                nearby = content[m.start():m.start() + 300]
                rm = re.search(r'response_model\s*=\s*(\w+)', nearby)
                if rm:
                    resp_type = rm.group(1)

                routes.append({
                    "method": http_method,
                    "path": _normalize_path(route_path),
                    "handler_name": handler_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": mw_chain,
                    "request_type": None,
                    "response_type": resp_type,
                    "framework": "fastapi",
                })

    # Django URL patterns
    if is_django:
        # path('url/', view, name='...')
        for m in re.finditer(
            r"path\s*\(\s*[r]?[\'\"]([^\'\"]+)[\'\"]\s*,\s*(\w+)",
            content
        ):
            route_path = m.group(1)
            handler_name = m.group(2)
            line_num = content[:m.start()].count('\n') + 1

            routes.append({
                "method": "ALL",
                "path": _normalize_path('/' + route_path),
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "django",
            })

        # re_path(r'^url/', view)
        for m in re.finditer(
            r"re_path\s*\(\s*[r]?[\'\"]([^\'\"]+)[\'\"]\s*,\s*(\w+)",
            content
        ):
            route_path = m.group(1)
            handler_name = m.group(2)
            line_num = content[:m.start()].count('\n') + 1

            routes.append({
                "method": "ALL",
                "path": _normalize_path('/' + route_path),
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "django",
            })

        # @api_view(['GET', 'POST'])
        for m in re.finditer(
            r"@api_view\s*\(\s*\[([^\]]*)\]",
            content
        ):
            methods_str = m.group(1)
            methods = re.findall(r'[\'"](\w+)[\'"]', methods_str)
            handler_name = _find_next_python_function(content, m.end())
            line_num = content[:m.start()].count('\n') + 1

            for method in methods:
                method_upper = method.upper()
                # Validate HTTP method
                if method_upper not in VALID_HTTP_METHODS_UPPER:
                    continue
                routes.append({
                    "method": method_upper,
                    "path": f"/{handler_name}",
                    "handler_name": handler_name,
                    "file": rel_path,
                    "line": line_num,
                    "middleware_chain": [],
                    "request_type": None,
                    "response_type": None,
                    "framework": "django",
                })

    return routes


def _find_next_python_function(content: str, offset: int) -> str:
    """Find the next Python function definition after offset."""
    remaining = content[offset:offset + 500]
    m = re.search(r'def\s+(\w+)', remaining)
    if m:
        return m.group(1)
    return "anonymous"


def _extract_python_decorator_middleware(
    content: str, offset: int, rel_path: str, line_num: int
) -> List[Dict[str, Any]]:
    """Extract middleware from Python decorators above a route handler."""
    middleware = []
    lines = content.split('\n')
    target_line = line_num - 1  # 0-indexed

    # Look at lines above the route decorator for other decorators
    for i in range(max(0, target_line - 5), target_line):
        if i >= len(lines):
            break
        stripped = lines[i].strip()
        if not stripped.startswith('@'):
            continue
        # Skip the route decorator itself
        if re.match(r'@\w+\.(get|post|put|delete|patch|route)\b', stripped):
            continue

        m = re.match(r'@(\w+)', stripped)
        if m:
            dec_name = m.group(1)
            mw_type = _classify_middleware(dec_name)
            if mw_type != "custom" or dec_name.lower() in {
                "login_required", "permission_required", "auth_required",
                "cache", "csrf", "cors", "throttle",
            }:
                middleware.append({
                    "name": dec_name,
                    "type": mw_type,
                    "file": rel_path,
                    "line": i + 1,
                })

    return middleware


def _extract_python_middleware(content: str, rel_path: str) -> List[Dict]:
    """Extract middleware declarations from Python files (Flask/Django/FastAPI)."""
    middleware = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Flask: app.before_request, app.after_request
        m = re.match(r'(?:app|server)\s*\.\s*(before_request|after_request)\s*\(\s*(\w+)', stripped)
        if m:
            mw_type = "auth" if any(p in m.group(2).lower() for p in AUTH_MIDDLEWARE_PATTERNS) else "custom"
            middleware.append({
                "name": m.group(2),
                "type": mw_type,
                "scope": m.group(1),
                "file": rel_path,
                "line": i + 1,
            })

        # Django MIDDLEWARE list entries
        m = re.match(r"[\'\"](\w[\w.]+)[\'\"]\s*,", stripped)
        if m and 'MIDDLEWARE' in content[:content.find(stripped) + len(stripped)]:
            mw_name = m.group(1).split('.')[-1]
            mw_type = _classify_middleware(mw_name)
            middleware.append({
                "name": mw_name,
                "type": mw_type,
                "scope": "global",
                "file": rel_path,
                "line": i + 1,
            })

        # FastAPI: app.add_middleware(...)
        m = re.match(r'app\s*\.\s*add_middleware\s*\(\s*(\w+)', stripped)
        if m:
            mw_name = m.group(1)
            mw_type = _classify_middleware(mw_name)
            middleware.append({
                "name": mw_name,
                "type": mw_type,
                "scope": "global",
                "file": rel_path,
                "line": i + 1,
            })

    return middleware


# ─── GraphQL ───────────────────────────────────────────────────

def _extract_graphql_schema(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract routes from GraphQL schema files (.graphql/.gql)."""
    routes = []

    # type Query { fieldName(args): ReturnType }
    for m in re.finditer(r'type\s+Query\s*\{([^}]+)\}', content, re.DOTALL):
        body = m.group(1)
        for field_m in re.finditer(r'(\w+)\s*(?:\([^)]*\))?\s*:\s*(\w+)', body):
            field_name = field_m.group(1)
            return_type = field_m.group(2)
            line_num = content[:field_m.start() + m.start(1)].count('\n') + 1
            routes.append({
                "method": "QUERY",
                "path": f"Query.{field_name}",
                "handler_name": f"{field_name}Resolver",
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": return_type,
                "framework": "graphql",
            })

    # type Mutation { fieldName(args): ReturnType }
    for m in re.finditer(r'type\s+Mutation\s*\{([^}]+)\}', content, re.DOTALL):
        body = m.group(1)
        for field_m in re.finditer(r'(\w+)\s*(?:\([^)]*\))?\s*:\s*(\w+)', body):
            field_name = field_m.group(1)
            return_type = field_m.group(2)
            line_num = content[:field_m.start() + m.start(1)].count('\n') + 1
            routes.append({
                "method": "MUTATION",
                "path": f"Mutation.{field_name}",
                "handler_name": f"{field_name}Resolver",
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": return_type,
                "framework": "graphql",
            })

    # type Subscription { fieldName(args): ReturnType }
    for m in re.finditer(r'type\s+Subscription\s*\{([^}]+)\}', content, re.DOTALL):
        body = m.group(1)
        for field_m in re.finditer(r'(\w+)\s*(?:\([^)]*\))?\s*:\s*(\w+)', body):
            field_name = field_m.group(1)
            return_type = field_m.group(2)
            line_num = content[:field_m.start() + m.start(1)].count('\n') + 1
            routes.append({
                "method": "SUBSCRIPTION",
                "path": f"Subscription.{field_name}",
                "handler_name": f"{field_name}Resolver",
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": return_type,
                "framework": "graphql",
            })

    return routes


def _extract_graphql_code(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract GraphQL resolvers from JS/TS code."""
    routes = []

    # Resolver map patterns: Query: { fieldName: (parent, args, ctx) => ... }
    for m in re.finditer(
        r'(Query|Mutation|Subscription)\s*:\s*\{',
        content
    ):
        parent_type = m.group(1)
        resolver_block = content[m.end():m.end() + 2000]
        # Find matching close brace
        depth = 1
        pos = 0
        while pos < len(resolver_block) and depth > 0:
            if resolver_block[pos] == '{':
                depth += 1
            elif resolver_block[pos] == '}':
                depth -= 1
            pos += 1
        resolver_block = resolver_block[:pos - 1]

        for field_m in re.finditer(r'(\w+)\s*[:=]\s*(?:async\s+)?\(', resolver_block):
            field_name = field_m.group(1)
            line_num = content[:m.end() + field_m.start()].count('\n') + 1
            routes.append({
                "method": parent_type.upper(),
                "path": f"{parent_type}.{field_name}",
                "handler_name": field_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "graphql",
            })

    # @Query / @Mutation decorators (TypeGraphQL)
    for m in re.finditer(
        r'@(Query|Mutation)\s*\(\s*(?:returns\s*=>\s*(\w+))?',
        content
    ):
        parent_type = m.group(1)
        return_type = m.group(2)
        handler_name = _find_next_js_function(content, m.end())
        line_num = content[:m.start()].count('\n') + 1
        routes.append({
            "method": parent_type.upper(),
            "path": f"{parent_type}.{handler_name}",
            "handler_name": handler_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": return_type,
            "framework": "graphql",
        })

    return routes


def _extract_graphql_python(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract GraphQL resolvers from Python code (Graphene, Strawberry, Ariadne)."""
    routes = []

    # Graphene: class Query(graphene.ObjectType): field = graphene.Field(...)
    for m in re.finditer(
        r'class\s+(\w+)\(.*graphene\.ObjectType.*\)\s*:',
        content
    ):
        class_name = m.group(1)
        class_body = content[m.end():m.end() + 3000]
        # Find fields
        for field_m in re.finditer(r'(\w+)\s*=\s*graphene\.(?:Field|String|Int|Float|Boolean|List)\b', class_body):
            field_name = field_m.group(1)
            line_num = content[:m.end() + field_m.start()].count('\n') + 1
            method_type = "QUERY" if class_name == "Query" else "MUTATION" if class_name == "Mutation" else class_name.upper()
            routes.append({
                "method": method_type,
                "path": f"{class_name}.{field_name}",
                "handler_name": f"resolve_{field_name}",
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "graphql",
            })

    # Strawberry: @query / @mutation decorators
    for m in re.finditer(r'@(query|mutation)\s*', content):
        op_type = m.group(1).upper()
        handler_name = _find_next_python_function(content, m.end())
        line_num = content[:m.start()].count('\n') + 1
        routes.append({
            "method": op_type,
            "path": f"{op_type}.{handler_name}",
            "handler_name": handler_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
            "framework": "graphql",
        })

    return routes


def _find_next_js_function(content: str, offset: int) -> str:
    """Find the next JS/TS function name after offset."""
    remaining = content[offset:offset + 300]
    # Named function
    m = re.search(r'(?:async\s+)?function\s+(\w+)', remaining)
    if m:
        return m.group(1)
    # Arrow or const
    m = re.search(r'(?:const|let|var)\s+(\w+)\s*=', remaining)
    if m:
        return m.group(1)
    # Class method
    m = re.search(r'(?:async\s+)?(\w+)\s*\(', remaining)
    if m:
        return m.group(1)
    return "anonymous"


# ─── gRPC ──────────────────────────────────────────────────────

def _extract_grpc_services(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract gRPC service definitions from .proto files."""
    routes = []

    # service ServiceName { rpc MethodName(RequestType) returns (ResponseType); }
    for m in re.finditer(r'service\s+(\w+)\s*\{([^}]+)\}', content, re.DOTALL):
        service_name = m.group(1)
        service_body = m.group(2)

        for rpc_m in re.finditer(
            r'rpc\s+(\w+)\s*\(\s*(?:stream\s+)?(\w+)\s*\)\s*returns\s*\(\s*(?:stream\s+)?(\w+)\s*\)',
            service_body
        ):
            method_name = rpc_m.group(1)
            request_type = rpc_m.group(2)
            response_type = rpc_m.group(3)
            line_num = content[:rpc_m.start() + m.start(2)].count('\n') + 1

            routes.append({
                "method": "GRPC",
                "path": f"/{service_name}/{method_name}",
                "handler_name": method_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": [],
                "request_type": request_type,
                "response_type": response_type,
                "framework": "grpc",
            })

    return routes


# ─── tRPC ──────────────────────────────────────────────────────

def _extract_trpc_routes(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract tRPC router definitions and procedure chains.

    Detects tRPC patterns including:
    - .query('name', ...) / .mutation('name', ...)
    - t.procedure / t.router
    - publicProcedure / protectedProcedure chains
    - router({ name: procedure }) definitions
    """
    routes = []

    # Detect tRPC or tRPC-like (procedure-based) imports / patterns
    is_trpc = bool(re.search(
        r'(?:from\s+[\'"]@trpc|import\s+.*@trpc|'
        r't\.procedure|t\.router|'
        r'\binitTRPC\b|'
        r'createTRPC(?:Router|ProxyClient|Next|React)|'
        r'\bpublicProcedure\b.*\.query\(|'
        r'\bpublicProcedure\b.*\.mutation\()',
        content
    ))

    if not is_trpc:
        return routes

    # tRPC procedure chains: publicProcedure.query('name', ...) or .mutation('name', ...)
    # Also: router({ name: procedure })
    for m in re.finditer(
        r'\.(query|mutation)\s*\(\s*[\'"](\w+)[\'"]',
        content
    ):
        proc_type = m.group(1).upper()
        proc_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Detect if this is a protected procedure
        mw_chain = []
        before = content[max(0, m.start() - 300):m.start()]
        if re.search(r'(?:protected|auth)Procedure', before):
            mw_chain.append({
                "name": "protectedProcedure",
                "type": "auth",
                "file": rel_path,
                "line": line_num,
            })

        routes.append({
            "method": proc_type,
            "path": proc_name,
            "handler_name": proc_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": mw_chain,
            "request_type": None,
            "response_type": None,
            "framework": "trpc",
        })

    # Router definitions: const appRouter = router({ ... })
    # Also: t.router({ ... })
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+Router)\s*=\s*(?:\w+\.)?router\s*\(',
        content
    ):
        router_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Try to extract procedure keys from router({ ... })
        router_body = content[m.end():m.end() + 5000]
        # Find matching closing paren
        depth = 1
        pos = 0
        while pos < len(router_body) and depth > 0:
            if router_body[pos] == '(':
                depth += 1
            elif router_body[pos] == ')':
                depth -= 1
            pos += 1
        router_body = router_body[:pos - 1]

        # Extract procedure name: value pairs from router object
        router_prefix = router_name.replace('Router', '')
        for pair_m in re.finditer(r'(\w+)\s*:\s*(\w+)', router_body):
            key = pair_m.group(1)
            value = pair_m.group(2)
            key_line = content[:m.end() + pair_m.start()].count('\n') + 1

            # Detect if the value references a protected procedure
            mw_chain = []
            proc_def = re.search(
                r'(?:const|let|var)\s+' + re.escape(value) +
                r'\s*=\s*(?:protected|auth)Procedure',
                content
            )
            if proc_def:
                mw_chain.append({
                    "name": "protectedProcedure",
                    "type": "auth",
                    "file": rel_path,
                    "line": content[:proc_def.start()].count('\n') + 1,
                })

            routes.append({
                "method": "PROCEDURE",
                "path": f"{router_prefix}.{key}" if router_prefix else key,
                "handler_name": value,
                "file": rel_path,
                "line": key_line,
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
                "framework": "trpc",
            })

        # Add the router itself
        routes.append({
            "method": "ROUTER",
            "path": router_name,
            "handler_name": router_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
            "framework": "trpc",
        })

    # .query() and .mutation() without string name (inline)
    for m in re.finditer(
        r'\.(query|mutation)\s*\(\s*(?:\{|async)',
        content
    ):
        proc_type = m.group(1).upper()
        line_num = content[:m.start()].count('\n') + 1
        # Try to find name from variable assignment
        before = content[max(0, m.start() - 200):m.start()]
        name_match = re.search(r'(\w+)\s*:\s*\w*Procedure$', before)
        handler_name = name_match.group(1) if name_match else f"anonymous_{proc_type.lower()}"

        # Detect if protected
        mw_chain = []
        if re.search(r'(?:protected|auth)Procedure', before):
            mw_chain.append({
                "name": "protectedProcedure",
                "type": "auth",
                "file": rel_path,
                "line": line_num,
            })

        routes.append({
            "method": proc_type,
            "path": handler_name,
            "handler_name": handler_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": mw_chain,
            "request_type": None,
            "response_type": None,
            "framework": "trpc",
        })

    # Detect t.procedure / t.router patterns (tRPC v10+)
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*t\.procedure',
        content
    ):
        var_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        routes.append({
            "method": "PROCEDURE",
            "path": var_name,
            "handler_name": var_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
            "framework": "trpc",
        })

    return routes


# ─── oRPC ──────────────────────────────────────────────────────

def _extract_orpc_routes(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract oRPC router definitions and procedure chains.

    Detects oRPC patterns including:
    - publicProcedure.input(...).output(...).handler(...)
    - protectedProcedure.input(...).output(...).handler(...)
    - adminProcedure chains
    - export const xxxRouter = { key: procedure, ... }
    - router({ name: procedure }) definitions
    - os.$context<Context>() base definitions
    """
    routes = []

    # Detect oRPC imports or patterns
    is_orpc = bool(re.search(
        r'(?:from\s+[\'"]@orpc|import\s+.*@orpc|'
        r'\bos\s*=\s*os\.|\bos\.\$context|'
        r'\bORPCError\b)',
        content
    ))

    # Also detect files that import procedure variables from oRPC modules
    has_procedures = bool(re.search(
        r'(?:public|protected|admin)Procedure\b',
        content
    ))

    if not is_orpc and not has_procedures:
        return routes

    # Track procedure variable names -> metadata
    procedures: Dict[str, Dict] = {}

    # Pattern 1: const varName = (public|protected|admin)Procedure
    #            .input(Schema).output(Schema).handler(async ...)
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*(public|protected|admin)Procedure',
        content
    ):
        var_name = m.group(1)
        proc_type = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Look for .input(), .output(), .handler() in the procedure chain
        # Search forward up to 800 chars for the full chain
        chain_text = content[m.start():m.start() + 800]
        input_match = re.search(r'\.input\s*\(\s*(\w+)', chain_text)
        output_match = re.search(r'\.output\s*\(\s*(\w+)', chain_text)
        has_handler = bool(re.search(r'\.handler\s*\(', chain_text))

        req_type = input_match.group(1) if input_match else None
        resp_type = output_match.group(1) if output_match else None

        is_auth = proc_type in ('protected', 'admin')
        mw_chain = []
        if is_auth:
            mw_chain.append({
                "name": f"{proc_type}Procedure",
                "type": "auth",
                "file": rel_path,
                "line": line_num,
            })

        procedures[var_name] = {
            "auth": is_auth,
            "input_schema": req_type,
            "output_schema": resp_type,
            "line": line_num,
        }

        if has_handler:
            routes.append({
                "method": "PROCEDURE",
                "path": var_name,
                "handler_name": var_name,
                "file": rel_path,
                "line": line_num,
                "middleware_chain": list(mw_chain),
                "request_type": req_type,
                "response_type": resp_type,
                "framework": "orpc",
            })

    # Pattern 2: export const xxxRouter = { key: procedureVar, ... }
    # Also handles: export const router = { name: xxxRouter, ... }
    for m in re.finditer(
        r'export\s+const\s+(\w+)\s*=\s*\{',
        content
    ):
        router_name = m.group(1)
        if not (router_name.endswith('Router') or router_name == 'router'):
            continue

        line_num = content[:m.start()].count('\n') + 1

        # Extract the object body
        obj_start = m.end()
        obj_body = content[obj_start:obj_start + 5000]
        # Find matching closing brace
        depth = 1
        pos = 0
        while pos < len(obj_body) and depth > 0:
            if obj_body[pos] == '{':
                depth += 1
            elif obj_body[pos] == '}':
                depth -= 1
            pos += 1
        obj_body = obj_body[:pos - 1]

        # Derive router prefix from name (likeRouter -> like)
        router_prefix = router_name.replace('Router', '') if router_name != 'router' else ''

        # Extract key: value pairs (handles nested objects by recursing)
        _extract_orpc_router_pairs(
            obj_body, procedures, router_prefix, rel_path, line_num, routes
        )

    # Pattern 3: .procedure('name', ...) chains
    for m in re.finditer(
        r'\.procedure\s*\(\s*[\'"](\w+)[\'"]',
        content
    ):
        proc_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        routes.append({
            "method": "PROCEDURE",
            "path": proc_name,
            "handler_name": proc_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
            "framework": "orpc",
        })

    # Pattern 4: Detect base procedure definitions (os.$context<Context>())
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*\w+\.\$context',
        content
    ):
        var_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        routes.append({
            "method": "BASE",
            "path": var_name,
            "handler_name": var_name,
            "file": rel_path,
            "line": line_num,
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
            "framework": "orpc",
        })

    return routes


def _extract_orpc_router_pairs(
    obj_body: str,
    procedures: Dict[str, Dict],
    prefix: str,
    rel_path: str,
    base_line: int,
    routes: List[Dict[str, Any]]
) -> None:
    """Extract procedure key:value pairs from an oRPC router object body,
    handling nested objects recursively."""
    # Match key: value pairs where value is a word (procedure reference or sub-router)
    for pair_m in re.finditer(r'(\w+)\s*:\s*(\w+)', obj_body):
        key = pair_m.group(1)
        value = pair_m.group(2)

        if value in procedures:
            # Value is a known procedure variable
            proc = procedures[value]
            route_path = f"{prefix}.{key}" if prefix else key

            mw_chain = []
            if proc["auth"]:
                mw_chain.append({
                    "name": "protectedProcedure",
                    "type": "auth",
                    "file": rel_path,
                    "line": proc["line"],
                })

            routes.append({
                "method": "PROCEDURE",
                "path": route_path,
                "handler_name": value,
                "file": rel_path,
                "line": base_line,
                "middleware_chain": mw_chain,
                "request_type": proc.get("input_schema"),
                "response_type": proc.get("output_schema"),
                "framework": "orpc",
            })
        elif value.endswith('Router'):
            # Value is a router reference - record as a router group
            route_path = f"{prefix}.{key}" if prefix else key
            routes.append({
                "method": "ROUTER",
                "path": route_path,
                "handler_name": value,
                "file": rel_path,
                "line": base_line,
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
                "framework": "orpc",
            })


# ─── Helpers ───────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """Normalize a route path (ensure leading /, remove trailing /)."""
    if not path:
        return "/"
    # Remove duplicate slashes
    path = re.sub(r'/+', '/', path)
    if not path.startswith('/'):
        path = '/' + path
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')
    return path


def _is_deprecated_route(route: Dict[str, Any]) -> bool:
    """Check if a route is marked as deprecated."""
    handler = route.get("handler_name") or ""
    # Common deprecation patterns
    if "deprecated" in handler.lower():
        return True
    # Check if the route path suggests deprecation
    path = route.get("path", "")
    if "/deprecated/" in path or "/v1/" in path:
        return True
    # This is a heuristic — in practice we'd check the file content for
    # @deprecated or deprecated: true comments near the route
    return False


def _build_route_groups(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group routes by path prefix (e.g., /api/users, /api/posts)."""
    groups: Dict[str, List[Dict]] = defaultdict(list)

    for route in routes:
        path = route.get("path", "/")
        parts = path.split('/')
        # Use first 2-3 path segments as the group key
        if len(parts) >= 3:
            group_key = '/'.join(parts[:3])
        elif len(parts) >= 2:
            group_key = '/'.join(parts[:2])
        else:
            group_key = "/"
        groups[group_key].append(route)

    result = []
    for prefix, group_routes in sorted(groups.items()):
        methods = set(r["method"] for r in group_routes)
        has_auth = any(r.get("auth_protected") for r in group_routes)
        result.append({
            "prefix": prefix,
            "route_count": len(group_routes),
            "methods": sorted(methods),
            "auth_protected": has_auth,
            "routes": [
                {"method": r["method"], "path": r["path"], "handler": r["handler_name"]}
                for r in group_routes
            ],
        })

    return result


def _generate_recommendations(
    routes: List[Dict[str, Any]],
    frameworks: Set[str],
    auth_protected: Set[str],
) -> List[Dict[str, Any]]:
    """Generate recommendations based on the API route analysis."""
    recommendations = []

    # No auth on mutation routes
    mutation_no_auth = [
        r for r in routes
        if r["method"] in {"POST", "PUT", "DELETE", "PATCH", "MUTATION"}
        and not r.get("auth_protected")
    ]
    if mutation_no_auth:
        recommendations.append({
            "type": "security",
            "severity": "critical",
            "message": f"{len(mutation_no_auth)} mutation routes have no auth middleware",
            "affected": [f"{r['method']} {r['path']}" for r in mutation_no_auth[:10]],
            "suggestion": "Add authentication middleware to all mutation endpoints.",
        })

    # No CORS middleware detected
    has_cors = any(
        any(mw.get("type") == "cors" for mw in r.get("middleware_chain", []))
        for r in routes
    )
    if not has_cors and any(f in frameworks for f in {"express", "fastify", "koa", "hono", "flask", "fastapi"}):
        recommendations.append({
            "type": "security",
            "severity": "warning",
            "message": "No CORS middleware detected on any route",
            "suggestion": "Add CORS configuration to control cross-origin access.",
        })

    # Deprecated routes
    deprecated = [r for r in routes if r.get("deprecated")]
    if deprecated:
        recommendations.append({
            "type": "maintenance",
            "severity": "info",
            "message": f"{len(deprecated)} deprecated routes found",
            "affected": [f"{r['method']} {r['path']}" for r in deprecated],
            "suggestion": "Plan migration away from deprecated endpoints and set sunset dates.",
        })

    # Too many routes in a single file
    file_route_count: Dict[str, int] = defaultdict(int)
    for r in routes:
        file_route_count[r["file"]] += 1

    large_files = {f: c for f, c in file_route_count.items() if c > 20}
    if large_files:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"{len(large_files)} file(s) contain more than 20 routes",
            "affected": list(large_files.keys()),
            "suggestion": "Split large route files into domain-specific modules.",
        })

    # REST best practices
    get_routes = [r for r in routes if r["method"] == "GET"]
    non_restful = [r for r in get_routes if "/get" in r["path"].lower() or "/list" in r["path"].lower()]
    if non_restful:
        recommendations.append({
            "type": "convention",
            "severity": "info",
            "message": f"{len(non_restful)} GET routes use non-RESTful path naming",
            "affected": [r["path"] for r in non_restful[:5]],
            "suggestion": "Use resource-based paths (e.g., /users instead of /getUsers).",
        })

    # Mixed frameworks warning
    if len(frameworks) > 2:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"Multiple web frameworks detected: {', '.join(sorted(frameworks))}",
            "suggestion": "Consider standardizing on one framework to reduce complexity.",
        })

    return recommendations


# ─── Tauri IPC ────────────────────────────────────────────────

def _extract_tauri_ipc_routes(content: str, rel_path: str) -> List[Dict]:
    """Extract Tauri IPC invoke() calls from frontend JS/TS/Svelte/Vue files.

    Pattern: invoke('command_name', { args }) or invoke("command_name")
    These map to Rust backend handlers decorated with #[tauri::command].
    """
    routes = []

    # Check if this file imports from @tauri-apps/api
    has_tauri_import = bool(re.search(
        r'(?:from\s+[\'"]@tauri-apps/api[\'"]|import\s+.*@tauri-apps/api|invoke\s*\()',
        content
    ))
    if not has_tauri_import:
        return routes

    # Match invoke('commandName') or invoke("commandName") with optional second arg
    for m in re.finditer(
        r'invoke\s*\(\s*[\'"](\w+)[\'"]\s*(?:,\s*\{[^}]*\})?\s*\)',
        content
    ):
        command_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        routes.append({
            "method": "IPC",
            "path": f"invoke://{command_name}",
            "handler_name": command_name,
            "file": rel_path,
            "line": line_num,
            "framework": "tauri",
            "middleware": [],
            "auth_required": False,
            "request_type": "ipc_call",
            "response_type": None,
        })

    return routes


def _extract_tauri_rust_commands(content: str, rel_path: str) -> List[Dict]:
    """Extract Tauri command handlers from Rust backend files.

    Pattern: #[tauri::command] followed by fn command_name(...)
    These are the Rust-side handlers that receive IPC calls from the frontend.
    """
    routes = []

    # Check if this file has tauri::command
    if 'tauri::command' not in content and 'tauri::command' not in content:
        return routes

    # Match #[tauri::command] followed by fn name(
    # Allow attributes between #[tauri::command] and fn
    for m in re.finditer(
        r'#\[tauri::command\]\s*(?:(?:#\[.*?\])\s*)*(?:pub\s+)?fn\s+(\w+)\s*\(',
        content
    ):
        command_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        routes.append({
            "method": "IPC_HANDLER",
            "path": f"invoke://{command_name}",
            "handler_name": command_name,
            "file": rel_path,
            "line": line_num,
            "framework": "tauri",
            "middleware": [],
            "auth_required": False,
            "request_type": "ipc_handler",
            "response_type": None,
        })

    return routes


def _extract_rust_http_routes(content: str, rel_path: str) -> List[Dict]:
    """Extract HTTP route handlers from Rust web framework code.

    Supports:
    - actix-web: #[get("/path")], #[post("/path")], web::resource(), web::route()
    - axum: .route("/path", get(handler)), Router::new().route()
    - warp: warp::path("segment"), warp::get()/post()
    - rocket: #[get("/path")], #[post("/path")]
    """
    routes = []

    # ─── actix-web / rocket: attribute-style routes ─────────────
    ACTIX_METHOD_MAP = {
        'get': 'GET', 'post': 'POST', 'put': 'PUT', 'delete': 'DELETE',
        'patch': 'PATCH', 'head': 'HEAD', 'options': 'OPTIONS',
    }
    for m in re.finditer(
        r'#\[(get|post|put|delete|patch|head|options)\s*\(\s*"([^"]+)"\s*\)\s*\]\s*(?:(?:#\[.*?\])\s*)*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(',
        content
    ):
        method_raw = m.group(1).lower()
        path = m.group(2)
        handler = m.group(3)
        line_num = content[:m.start()].count('\n') + 1

        fw = "actix-web"
        if 'rocket' in content and 'actix' not in content:
            fw = "rocket"

        routes.append({
            "method": ACTIX_METHOD_MAP.get(method_raw, method_raw.upper()),
            "path": path,
            "handler_name": handler,
            "file": rel_path,
            "line": line_num,
            "framework": fw,
            "middleware": [],
            "auth_required": False,
            "request_type": "http_handler",
            "response_type": None,
        })

    # ─── actix-web: web::resource().route().method() ─────────────
    for m in re.finditer(
        r'\.resource\s*\(\s*"([^"]+)"\s*\)',
        content
    ):
        path = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        routes.append({
            "method": "RESOURCE",
            "path": path,
            "handler_name": None,
            "file": rel_path,
            "line": line_num,
            "framework": "actix-web",
            "middleware": [],
            "auth_required": False,
            "request_type": "resource_route",
            "response_type": None,
        })

    # ─── axum: .route("/path", get(handler)) ─────────────
    for m in re.finditer(
        r'\.route\s*\(\s*"([^"]+)"\s*,\s*(get|post|put|delete|patch|head|options|any)\s*\(\s*(\w+)\s*\)',
        content
    ):
        path = m.group(1)
        method_raw = m.group(2).lower()
        handler = m.group(3)
        line_num = content[:m.start()].count('\n') + 1

        routes.append({
            "method": method_raw.upper(),
            "path": path,
            "handler_name": handler,
            "file": rel_path,
            "line": line_num,
            "framework": "axum",
            "middleware": [],
            "auth_required": False,
            "request_type": "http_handler",
            "response_type": None,
        })

    # ─── warp: warp::path("segment") ─────────────
    if 'warp::' in content:
        warp_paths = re.findall(r'warp::path\s*\(\s*"([^"]+)"\s*\)', content)
        if warp_paths:
            for segment in warp_paths[:20]:
                idx = content.find(f'warp::path("{segment}")')
                line_num = content[:idx].count('\n') + 1 if idx >= 0 else 0
                routes.append({
                    "method": "FILTER",
                    "path": f"/{segment}",
                    "handler_name": None,
                    "file": rel_path,
                    "line": line_num,
                    "framework": "warp",
                    "middleware": [],
                    "auth_required": False,
                    "request_type": "path_filter",
                    "response_type": None,
                })

    return routes


# ─── Go Route Extraction ─────────────────────────────────────

# Go HTTP method names as they appear in framework calls
_GO_METHODS_UPPER = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
_GO_METHODS_LOWER = {"get", "post", "put", "delete", "patch", "head", "options"}


def _extract_go_routes(
    content: str, rel_path: str, frameworks: Set[str]
) -> List[Dict[str, Any]]:
    """Extract API routes from Go source files.

    Supports:
    - net/http stdlib: http.HandleFunc, http.Handle, mux.HandleFunc, mux.Handle
    - Gin:             r.GET/POST/PUT/DELETE/PATCH("/path", handler)
    - Echo:            e.GET/POST/PUT/DELETE/PATCH("/path", handler)
    - Chi:             r.Get/Post/Put/Delete("/path", handler), r.Route("/path", func...)
    - Fiber:           app.Get/Post/Put/Delete("/path", handler)
    - httprouter:      router.GET/POST/PUT/DELETE/PATCH("/path", handler)
                       router.Handle("METHOD", "/path", handler)
    """
    routes: List[Dict[str, Any]] = []

    # ─── Detect which Go frameworks are in use via imports ─────
    is_gin = bool(re.search(r'"github\.com/gin-gonic/gin"', content))
    is_echo = bool(re.search(r'"github\.com/labstack/echo', content))
    is_chi = bool(re.search(r'"github\.com/go-chi/chi', content))
    is_fiber = bool(re.search(r'"github\.com/gofiber/fiber', content))
    is_httprouter = bool(re.search(r'"github\.com/julienschmidt/httprouter"', content))
    is_net_http = bool(re.search(r'"net/http"', content))

    # Track router variable names and their prefixes (for group/prefix support)
    # Gin:  r := gin.Default(); g := r.Group("/api")
    # Echo: g := e.Group("/api")
    # Chi:  r.Route("/api", func(r chi.Router) { ... })
    router_groups: Dict[str, str] = {}  # var_name → prefix

    # ─── 1. net/http stdlib: http.HandleFunc("/path", handler) ─
    for m in re.finditer(
        r'(?:http|mux)\.(?:HandleFunc|Handle)\s*\(\s*"([^"]+)"\s*,\s*(\w+)',
        content
    ):
        path = m.group(1)
        handler = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        routes.append({
            "method": "GET",  # HandleFunc defaults to GET; Handle is handler-based
            "path": _normalize_path(path),
            "handler_name": handler,
            "file": rel_path,
            "line": line_num,
            "framework": "go-net-http",
            "middleware_chain": [],
            "request_type": None,
            "response_type": None,
        })
        frameworks.add("go-net-http")

    # ─── 2. Gin: r.GET("/path", handler) ────────────────────────
    # Also matches router.GET, g.GET, etc.
    if is_gin:
        # Detect Group assignments: apiGroup := r.Group("/api")
        for gm in re.finditer(
            r'(\w+)\s*(?::=|=)\s*\w+\.Group\s*\(\s*"([^"]*)"',
            content
        ):
            router_groups[gm.group(1)] = gm.group(2)

        for m in re.finditer(
            r'(\w+)\s*\.\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"([^"]+)"',
            content
        ):
            obj_name = m.group(1)
            method = m.group(2).upper()
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            # Parse the full argument list after the path to find handler & middleware
            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            # Apply group prefix if available
            prefix = router_groups.get(obj_name, "")
            full_path = _normalize_path(prefix + path)

            routes.append({
                "method": method,
                "path": full_path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "gin",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("gin")

    # ─── 3. Echo: e.GET("/path", handler) ──────────────────────
    if is_echo:
        # Detect Echo Group: g := e.Group("/api")
        for gm in re.finditer(
            r'(\w+)\s*(?::=|=)\s*\w+\.Group\s*\(\s*"([^"]*)"',
            content
        ):
            router_groups[gm.group(1)] = gm.group(2)

        for m in re.finditer(
            r'(\w+)\s*\.\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"([^"]+)"',
            content
        ):
            obj_name = m.group(1)
            method = m.group(2).upper()
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            prefix = router_groups.get(obj_name, "")
            full_path = _normalize_path(prefix + path)

            routes.append({
                "method": method,
                "path": full_path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "echo",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("echo")

    # ─── 4. Chi: r.Get("/path", handler), r.Route("/path", fn) ─
    if is_chi:
        # Chi uses Title-case methods: r.Get, r.Post, etc.
        # Detect Chi Route groups
        for rm in re.finditer(
            r'(\w+)\s*:=?\s*\w+\.Route\s*\(\s*"([^"]+)"',
            content
        ):
            router_groups[rm.group(1)] = rm.group(2)

        # Collect the character ranges of r.Route(...) closure blocks
        # so we can exclude those inner routes from the top-level scan.
        # Ranges start after the opening { so the Route call itself is NOT excluded.
        route_closure_ranges: List[tuple] = []
        for m in re.finditer(
            r'(\w+)\s*\.\s*Route\s*\(\s*"([^"]+)"\s*,\s*(?:func\s*\([^)]*\)\s*\{)',
            content
        ):
            closure_start = m.end()  # just past the opening {
            block = _extract_go_block(content, closure_start)
            if block is not None:
                # Range starts at m.end() so the Route call itself is NOT inside the range
                route_closure_ranges.append((m.end(), closure_start + len(block)))

        for m in re.finditer(
            r'(\w+)\s*\.\s*(Get|Post|Put|Delete|Patch|Head|Options)\s*\(\s*"([^"]+)"',
            content
        ):
            # Skip matches inside r.Route(...) closures — they'll be handled below
            if any(lo <= m.start() < hi for lo, hi in route_closure_ranges):
                continue

            obj_name = m.group(1)
            method = m.group(2).upper()
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            prefix = router_groups.get(obj_name, "")
            full_path = _normalize_path(prefix + path)

            routes.append({
                "method": method,
                "path": full_path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "chi",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("chi")

        # Chi r.Route("/path", func(r chi.Router) { r.Get(...), r.Post(...) })
        # Also handles nested Route closures recursively
        def _extract_chi_route_block(block_text: str, prefix: str, rel: str, ln: int):
            """Recursively extract Chi routes from a Route closure block."""
            # Collect nested Route closure ranges to skip from top-level scan
            nested_ranges: List[tuple] = []
            for nm in re.finditer(
                r'(\w+)\s*\.\s*Route\s*\(\s*"([^"]+)"\s*,\s*(?:func\s*\([^)]*\)\s*\{)',
                block_text
            ):
                nested_prefix = nm.group(2)
                nested_closure_start = nm.end()
                nested_block = _extract_go_block(block_text, nested_closure_start)
                if nested_block is not None:
                    nested_ranges.append((nm.start(), nested_closure_start + len(nested_block)))
                    # Recurse into nested Route
                    _extract_chi_route_block(
                        nested_block,
                        _normalize_path(prefix + nested_prefix),
                        rel, ln
                    )

            # Match method calls, skipping those inside nested Route closures
            for im in re.finditer(
                r'\.\s*(Get|Post|Put|Delete|Patch|Head|Options)\s*\(\s*"([^"]+)"',
                block_text
            ):
                if any(lo <= im.start() < hi for lo, hi in nested_ranges):
                    continue
                inner_method = im.group(1).upper()
                inner_path = im.group(2)
                inner_handler, inner_mw = _parse_go_route_args(
                    block_text, im.end(), rel, ln
                )
                full_path = _normalize_path(prefix + inner_path)
                routes.append({
                    "method": inner_method,
                    "path": full_path,
                    "handler_name": inner_handler,
                    "file": rel,
                    "line": ln,
                    "framework": "chi",
                    "middleware_chain": inner_mw,
                    "request_type": None,
                    "response_type": None,
                })

        for m in re.finditer(
            r'(\w+)\s*\.\s*Route\s*\(\s*"([^"]+)"\s*,\s*(?:func\s*\([^)]*\)\s*\{)',
            content
        ):
            # Skip nested Route calls that are inside an outer Route closure
            # (they'll be handled recursively by _extract_chi_route_block)
            if any(lo <= m.start() < hi for lo, hi in route_closure_ranges):
                continue
            route_path = m.group(2)
            line_num = content[:m.start()].count('\n') + 1
            closure_start = m.end()
            block = _extract_go_block(content, closure_start)
            if block:
                _extract_chi_route_block(block, route_path, rel_path, line_num)

    # ─── 5. Fiber: app.Get("/path", handler) ────────────────────
    if is_fiber:
        # Fiber uses Title-case methods like Chi
        # Detect Fiber Group: g := app.Group("/api")
        for gm in re.finditer(
            r'(\w+)\s*(?::=|=)\s*\w+\.Group\s*\(\s*"([^"]*)"',
            content
        ):
            router_groups[gm.group(1)] = gm.group(2)

        for m in re.finditer(
            r'(\w+)\s*\.\s*(Get|Post|Put|Delete|Patch|Head|Options|All)\s*\(\s*"([^"]+)"',
            content
        ):
            obj_name = m.group(1)
            method_raw = m.group(2)
            method = method_raw.upper() if method_raw != "All" else "ALL"
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            prefix = router_groups.get(obj_name, "")
            full_path = _normalize_path(prefix + path)

            routes.append({
                "method": method,
                "path": full_path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "fiber",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("fiber")

    # ─── 6. httprouter: router.GET("/path", handler) ────────────
    if is_httprouter:
        for m in re.finditer(
            r'(\w+)\s*\.\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"([^"]+)"',
            content
        ):
            obj_name = m.group(1)
            method = m.group(2).upper()
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            routes.append({
                "method": method,
                "path": _normalize_path(path),
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "httprouter",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("httprouter")

        # httprouter.Handle("METHOD", "/path", handler)
        for m in re.finditer(
            r'(\w+)\s*\.\s*Handle\s*\(\s*"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)"\s*,\s*"([^"]+)"\s*,\s*(\w+)',
            content
        ):
            method = m.group(2).upper()
            path = m.group(3)
            handler = m.group(4)
            line_num = content[:m.start()].count('\n') + 1
            routes.append({
                "method": method,
                "path": _normalize_path(path),
                "handler_name": handler,
                "file": rel_path,
                "line": line_num,
                "framework": "httprouter",
                "middleware_chain": [],
                "request_type": None,
                "response_type": None,
            })
            frameworks.add("httprouter")

    # ─── Fallback: generic Go HTTP method calls ─────────────────
    # If no specific framework was detected but the file uses net/http
    # and has method calls, catch them as generic go-http routes.
    if not is_gin and not is_echo and not is_chi and not is_fiber and not is_httprouter and is_net_http:
        # Upper-case method calls (e.g., router.GET, r.POST)
        for m in re.finditer(
            r'(\w+)\s*\.\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"([^"]+)"',
            content
        ):
            obj_name = m.group(1)
            # Skip if obj is a well-known non-router
            if obj_name in ("http", "mux"):
                continue  # already handled above
            method = m.group(2).upper()
            path = m.group(3)
            line_num = content[:m.start()].count('\n') + 1

            # Skip if already captured
            if any(r["file"] == rel_path and r["line"] == line_num and r["method"] == method for r in routes):
                continue

            handler_name, mw_chain = _parse_go_route_args(content, m.end(), rel_path, line_num)

            prefix = router_groups.get(obj_name, "")
            full_path = _normalize_path(prefix + path)

            routes.append({
                "method": method,
                "path": full_path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line_num,
                "framework": "go-http",
                "middleware_chain": mw_chain,
                "request_type": None,
                "response_type": None,
            })

    return routes


def _parse_go_route_args(
    content: str, start_pos: int, rel_path: str, line_num: int
) -> tuple:
    """Parse Go route call arguments after the path string.

    Given that the regex matched up to the closing quote of the path,
    parse the remaining arguments to determine the final handler name
    and any middleware in between.

    Returns (handler_name, middleware_chain).
    For example: r.GET("/path", authMiddleware(), logger(), finalHandler)
    → ("finalHandler", [{"name": "authMiddleware", ...}, {"name": "logger", ...}])
    """
    # Find the opening paren of the call (search backward from current position)
    paren_start = content.rfind('(', 0, start_pos + 1)
    if paren_start < 0:
        return ("anonymous", [])

    # Find the matching closing paren
    depth = 1
    pos = paren_start + 1
    while pos < len(content) and depth > 0:
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
        pos += 1

    args_section = content[paren_start + 1:pos - 1]
    args = _split_args(args_section)

    # args[0] should be the path string, remaining args are handlers/middleware
    # The last non-path arg is the handler; args between are middleware
    handler_name = "anonymous"
    middleware: List[Dict[str, Any]] = []

    if len(args) <= 1:
        # Only path, no handler arg (shouldn't happen in valid Go, but be safe)
        return (handler_name, middleware)

    # Collect all non-path arguments
    non_path_args = [a.strip() for a in args[1:] if a.strip()]

    if not non_path_args:
        return (handler_name, middleware)

    # The last argument is the final handler
    last_arg = non_path_args[-1]
    # Extract the identifier name from the handler arg
    m = re.match(r'(\w+)', last_arg)
    if m:
        handler_name = m.group(1)

    # Everything before the last arg is middleware
    for arg in non_path_args[:-1]:
        arg = arg.strip()
        if not arg:
            continue
        # Strip function call parens: AuthMiddleware() → AuthMiddleware
        bare_name = re.sub(r'\(.*\)', '', arg).strip()
        if not bare_name:
            bare_name = arg
        mw_type = _classify_middleware(bare_name)
        middleware.append({
            "name": bare_name,
            "type": mw_type,
            "file": rel_path,
            "line": line_num,
        })

    return (handler_name, middleware)


def _go_file_framework(
    content: str,
    is_gin: bool, is_echo: bool, is_chi: bool,
    is_fiber: bool, is_httprouter: bool, is_net_http: bool
) -> str:
    """Determine the dominant Go framework for a file based on imports."""
    if is_gin:
        return "gin"
    if is_echo:
        return "echo"
    if is_chi:
        return "chi"
    if is_fiber:
        return "fiber"
    if is_httprouter:
        return "httprouter"
    if is_net_http:
        return "go-net-http"
    return "go"


def _extract_go_block(content: str, start: int) -> Optional[str]:
    """Extract a balanced curly-brace block starting at `start` (which should be
    just past the opening brace). Returns the block content without outer braces,
    or None if the block can't be found."""
    if start >= len(content):
        return None
    depth = 1
    pos = start
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    if depth == 0:
        return content[start:pos - 1]
    return None


def _detect_go_frameworks(workspace: str, frameworks: Set[str]) -> None:
    """Detect Go web frameworks from go.mod dependency declarations."""
    go_mod_path = os.path.join(workspace, "go.mod")
    if not os.path.isfile(go_mod_path):
        return

    try:
        with open(go_mod_path, 'r', encoding='utf-8', errors='ignore') as f:
            go_mod = f.read()
    except IOError:
        return

    # Map of import path substrings → framework names
    go_fw_map = {
        "github.com/gin-gonic/gin": "gin",
        "github.com/labstack/echo": "echo",
        "github.com/go-chi/chi": "chi",
        "github.com/go-chi/chi/v5": "chi",
        "github.com/gofiber/fiber": "fiber",
        "github.com/julienschmidt/httprouter": "httprouter",
    }

    for import_path, fw_name in go_fw_map.items():
        if import_path in go_mod:
            frameworks.add(fw_name)

    # If go.mod exists but no specific framework, note standard library
    if not any(fw in frameworks for fw in ("gin", "echo", "chi", "fiber", "httprouter")):
        frameworks.add("go-net-http")


# ─── PHP / Laravel Route Extraction ──────────────────────────

def _extract_php_routes(content: str, rel_path: str, frameworks_detected: Set[str]) -> List[Dict[str, Any]]:
    """Extract API routes from PHP source files (Laravel, Symfony, Slim)."""
    routes: List[Dict[str, Any]] = []

    # ─── Laravel Route Definitions ────────────────────────────
    # Route::get('/path', [Controller::class, 'method'])
    # Route::post('/path', 'Controller@method')
    # Route::put('/path', 'Controller@method')
    # Route::delete('/path', 'Controller@method')
    # Route::patch('/path', 'Controller@method')
    # Route::options('/path', 'Controller@method')
    # Route::any('/path', ...)
    # Route::resource('/path', 'Controller')
    # Route::apiResource('/path', 'Controller')
    # Route::group([...], function() { ... })

    # Pattern 1: Route::method('/path', [ControllerClass::class, 'methodName'])
    laravel_array_pattern = re.compile(
        r"Route::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)['\"]"
        r"\s*,\s*\[?\s*([\w\\]+)::class\s*,\s*['\"](\w+)['\"]"
    )
    for m in laravel_array_pattern.finditer(content):
        method = m.group(1).upper()
        path = m.group(2)
        controller = m.group(3).rsplit('\\', 1)[-1]
        handler = m.group(4)
        line = content[:m.start()].count('\n') + 1
        routes.append({
            "method": method,
            "path": path,
            "handler_name": f"{controller}@{handler}",
            "file": rel_path,
            "line": line,
            "framework": "laravel",
            "middleware": [],
            "auth_required": False,
            "request_type": None,
            "response_type": None,
        })
        frameworks_detected.add("laravel")

    # Pattern 2: Route::method('/path', 'Controller@method')
    laravel_at_pattern = re.compile(
        r"Route::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)['\"]"
        r"\s*,\s*['\"]([\w\\]+)@(\w+)['\"]"
    )
    for m in laravel_at_pattern.finditer(content):
        # Skip if already matched by array pattern (which is more specific)
        if any(r.get("file") == rel_path and r.get("path") == m.group(2) and r.get("method") == m.group(1).upper() for r in routes):
            continue
        method = m.group(1).upper()
        path = m.group(2)
        controller = m.group(3).rsplit('\\', 1)[-1]
        handler = m.group(4)
        line = content[:m.start()].count('\n') + 1
        routes.append({
            "method": method,
            "path": path,
            "handler_name": f"{controller}@{handler}",
            "file": rel_path,
            "line": line,
            "framework": "laravel",
            "middleware": [],
            "auth_required": False,
            "request_type": None,
            "response_type": None,
        })
        frameworks_detected.add("laravel")

    # Pattern 3: Route::resource and Route::apiResource
    laravel_resource_pattern = re.compile(
        r"Route::(resource|apiResource)\s*\(\s*['\"]([^'\"]+)['\"]"
        r"\s*,\s*['\"]?([\w\\]+)['\"]?"
    )
    resource_methods_map = {
        "resource": ["GET", "GET", "GET", "POST", "PUT", "PATCH", "DELETE"],
        "apiResource": ["GET", "POST", "GET", "PUT", "PATCH", "DELETE"],
    }
    resource_paths_map = {
        "resource": ["", "/create", "/{id}", "", "/{id}/edit", "/{id}"],
        "apiResource": ["", "", "/{id}", "/{id}", "/{id}"],
    }
    for m in laravel_resource_pattern.finditer(content):
        resource_type = m.group(1)
        base_path = m.group(2)
        controller = m.group(3).rsplit('\\', 1)[-1]
        line = content[:m.start()].count('\n') + 1

        methods = resource_methods_map.get(resource_type, ["GET"])
        paths = resource_paths_map.get(resource_type, [""])
        handlers = ["index", "create", "show", "store", "edit", "update", "destroy"] if resource_type == "resource" else ["index", "store", "show", "update", "destroy"]

        for i, (http_method, sub_path, handler) in enumerate(zip(methods, paths, handlers)):
            full_path = base_path + sub_path
            routes.append({
                "method": http_method,
                "path": full_path,
                "handler_name": f"{controller}@{handler}",
                "file": rel_path,
                "line": line,
                "framework": "laravel",
                "middleware": [],
                "auth_required": False,
                "request_type": "resource",
                "response_type": None,
            })
        frameworks_detected.add("laravel")

    # Pattern 4: Route::group(['prefix' => '...', 'middleware' => '...'], function() { })
    laravel_group_pattern = re.compile(
        r"Route::group\s*\(\s*\[([^\]]+)\]\s*,\s*function"
    )
    for m in laravel_group_pattern.finditer(content):
        group_body = m.group(1)
        line = content[:m.start()].count('\n') + 1
        prefix = ""
        middleware_names = []

        # Extract prefix
        prefix_match = re.search(r"'prefix'\s*=>\s*'([^']+)'", group_body)
        if prefix_match:
            prefix = prefix_match.group(1)
        else:
            prefix_match = re.search(r'"prefix"\s*=>\s*"([^"]+)"', group_body)
            if prefix_match:
                prefix = prefix_match.group(1)

        # Extract middleware
        mw_match = re.search(r"'middleware'\s*=>\s*'([^']+)'", group_body)
        if mw_match:
            middleware_names = [mw_match.group(1)]
        else:
            mw_match = re.search(r'"middleware"\s*=>\s*"([^"]+)"', group_body)
            if mw_match:
                middleware_names = [mw_match.group(1)]

        routes.append({
            "method": "GROUP",
            "path": f"/{prefix}" if prefix else "/",
            "handler_name": None,
            "file": rel_path,
            "line": line,
            "framework": "laravel",
            "middleware": middleware_names,
            "auth_required": any(mw in AUTH_MIDDLEWARE_PATTERNS for mw in middleware_names),
            "request_type": "route_group",
            "response_type": None,
        })
        frameworks_detected.add("laravel")

    # ─── Symfony Route Definitions ─────────────────────────────
    # Attributes: #[Route('/path', name: 'route_name', methods: ['GET'])]
    symfony_attr_pattern = re.compile(
        r"#\[Route\s*\(\s*['\"]([^'\"]+)['\"]"
        r"(?:\s*,\s*name:\s*['\"]([^'\"]*)['\"])?"
        r"(?:\s*,\s*methods:\s*\[([^\]]+)\])?"
    )
    for m in symfony_attr_pattern.finditer(content):
        path = m.group(1)
        methods_str = m.group(3) or "'GET'"
        line = content[:m.start()].count('\n') + 1

        # Parse methods
        methods = [mth.strip().strip("'\"") for mth in methods_str.split(',')]
        methods = [mth for mth in methods if mth in VALID_HTTP_METHODS_UPPER or mth.upper() in VALID_HTTP_METHODS_UPPER]
        if not methods:
            methods = ["GET"]

        # Find the function this attribute is attached to
        fn_match = re.search(r'function\s+(\w+)\s*\(', content[m.end():m.end() + 200])
        handler_name = fn_match.group(1) if fn_match else None

        for http_method in methods:
            routes.append({
                "method": http_method.upper(),
                "path": path,
                "handler_name": handler_name,
                "file": rel_path,
                "line": line,
                "framework": "symfony",
                "middleware": [],
                "auth_required": False,
                "request_type": None,
                "response_type": None,
            })
        frameworks_detected.add("symfony")

    # ─── Slim Framework Routes ────────────────────────────────
    # $app->get('/path', function ($request, $response) { ... })
    # $app->get('/path', ClassName::class . ':methodName')
    slim_pattern = re.compile(
        r"\$app->(get|post|put|delete|patch|options)\s*\(\s*['\"]([^'\"]+)['\"]"
    )
    for m in slim_pattern.finditer(content):
        # Skip if already matched as Laravel
        if any(r.get("file") == rel_path and r.get("path") == m.group(2) and r.get("method") == m.group(1).upper() for r in routes):
            continue
        method = m.group(1).upper()
        path = m.group(2)
        line = content[:m.start()].count('\n') + 1
        routes.append({
            "method": method,
            "path": path,
            "handler_name": None,
            "file": rel_path,
            "line": line,
            "framework": "slim",
            "middleware": [],
            "auth_required": False,
            "request_type": None,
            "response_type": None,
        })
        frameworks_detected.add("slim")

    return routes


def _extract_php_middleware(content: str, rel_path: str) -> List[Dict]:
    """Extract middleware from PHP source files (Laravel)."""
    middleware: List[Dict] = []

    # Laravel middleware registration
    # ->middleware('auth')
    # ->middleware(['auth', 'throttle'])
    for m in re.finditer(r"->middleware\s*\(\s*['\"]([\w.]+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        mw_name = m.group(1)
        middleware.append({
            "name": mw_name,
            "type": "laravel_middleware",
            "file": rel_path,
            "line": line,
            "is_auth": mw_name in AUTH_MIDDLEWARE_PATTERNS,
            "is_cors": mw_name in CORS_MIDDLEWARE_PATTERNS,
            "is_rate_limit": mw_name in RATE_LIMIT_PATTERNS,
        })

    # Laravel $middleware / $middlewareGroups / $routeMiddleware in Kernel.php
    for m in re.finditer(r"'(\w+)'\s*=>\s*[\w\\]+Middleware", content):
        line = content[:m.start()].count('\n') + 1
        middleware.append({
            "name": m.group(1),
            "type": "laravel_middleware_alias",
            "file": rel_path,
            "line": line,
            "is_auth": m.group(1) in AUTH_MIDDLEWARE_PATTERNS,
            "is_cors": False,
            "is_rate_limit": False,
        })

    return middleware


# ─── Ruby: Rails route extraction ─────────────────────────────────

def _extract_rails_routes(content: str, rel_path: str, frameworks_detected: Set[str]) -> List[Dict[str, Any]]:
    """Extract routes from Rails routes.rb files."""
    routes = []
    is_routes_file = 'routes.rb' in rel_path or 'config/routes' in rel_path
    if not is_routes_file:
        return routes

    frameworks_detected.add("rails")

    current_namespace = ""

    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        ns_match = re.match(r'\s*namespace\s+:(\w+)\s+do', line)
        if ns_match:
            current_namespace = ns_match.group(1)
            continue

        if stripped == 'end' and current_namespace:
            current_namespace = ""
            continue

        http_match = re.match(
            r"\s*(get|post|put|patch|delete)\s+['\"]([^'\"]+)['\"]" +
            r"(?:\s*,\s*to:\s*['\"]([^'\"]+)['\"])?",
            line
        )
        if http_match:
            method = http_match.group(1).upper()
            path = http_match.group(2)
            handler = http_match.group(3) or ""
            if current_namespace:
                path = f"/{current_namespace}{path}"
            routes.append({
                "method": method,
                "path": path,
                "handler": handler,
                "handler_name": handler.split('#')[-1] if '#' in handler else handler,
                "file": rel_path,
                "line": i,
                "framework": "rails",
                "group": current_namespace or "default",
                "auth_required": False,
            })
            continue

        res_match = re.match(r"\s*resources\s+:(\w+)", line)
        if res_match:
            resource_name = res_match.group(1)
            base_path = f"/{resource_name}"
            if current_namespace:
                base_path = f"/{current_namespace}{base_path}"
            for m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                action_map = {"GET": "index", "POST": "create", "PUT": "update",
                              "PATCH": "update", "DELETE": "destroy"}
                action = action_map.get(m, "show")
                routes.append({
                    "method": m,
                    "path": base_path,
                    "handler": f"{resource_name}#{action}",
                    "handler_name": action,
                    "file": rel_path,
                    "line": i,
                    "framework": "rails",
                    "group": current_namespace or "default",
                    "auth_required": False,
                    "resource": resource_name,
                })
            continue

        root_match = re.match(r"\s*root\s+['\"]([^'\"]+)['\"]", line)
        if root_match:
            handler = root_match.group(1)
            routes.append({
                "method": "GET",
                "path": "/",
                "handler": handler,
                "handler_name": handler.split('#')[-1] if '#' in handler else handler,
                "file": rel_path,
                "line": i,
                "framework": "rails",
                "group": "default",
                "auth_required": False,
            })

    return routes


# ─── Elixir: Phoenix route extraction ──────────────────────────────

def _extract_phoenix_routes(content: str, rel_path: str, frameworks_detected: Set[str]) -> List[Dict[str, Any]]:
    """Extract routes from Phoenix router.ex files."""
    routes = []
    is_router = 'router.ex' in rel_path or 'router.exs' in rel_path
    if not is_router:
        return routes

    frameworks_detected.add("phoenix")

    current_scope = ""
    current_pipe = ""

    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        scope_match = re.match(r'\s*scope\s+"([^"]+)"', line)
        if scope_match:
            current_scope = scope_match.group(1)
            continue

        pipe_match = re.match(r'\s*pipe_through\s+:([\w]+)', line)
        if pipe_match:
            current_pipe = pipe_match.group(1)
            continue

        http_match = re.match(
            r'\s*(get|post|put|patch|delete)\s+"([^"]+)"\s*,\s*([\w.]+)\s*,\s*:(\w+)',
            line
        )
        if http_match:
            method = http_match.group(1).upper()
            path = http_match.group(2)
            controller = http_match.group(3)
            action = http_match.group(4)
            if current_scope:
                path = f"{current_scope}{path}"
            routes.append({
                "method": method,
                "path": path,
                "handler": f"{controller}.{action}",
                "handler_name": action,
                "file": rel_path,
                "line": i,
                "framework": "phoenix",
                "group": current_scope or "default",
                "middleware": [current_pipe] if current_pipe else [],
                "auth_required": current_pipe in ("authenticate", "auth", "require_login"),
            })
            continue

        res_match = re.match(r'\s*resources\s+"([^"]+)"\s*,\s*([\w.]+)', line)
        if res_match:
            path = res_match.group(1)
            controller = res_match.group(2)
            if current_scope:
                path = f"{current_scope}{path}"
            for m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                action = {"GET": "index", "POST": "create", "PUT": "update",
                          "PATCH": "update", "DELETE": "delete"}.get(m, "show")
                routes.append({
                    "method": m,
                    "path": path,
                    "handler": f"{controller}.{action}",
                    "handler_name": action,
                    "file": rel_path,
                    "line": i,
                    "framework": "phoenix",
                    "group": current_scope or "default",
                    "middleware": [current_pipe] if current_pipe else [],
                    "auth_required": False,
                    "resource": True,
                })

        if stripped == 'end' and current_scope:
            current_scope = ""
            current_pipe = ""

    return routes

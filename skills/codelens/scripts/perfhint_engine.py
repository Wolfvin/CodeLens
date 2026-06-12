"""
Performance Hint Detection Engine for CodeLens — v5
Detects performance anti-patterns, inefficient code, and optimization
opportunities across 8 categories of common performance pitfalls.

Answers: "Are there any performance anti-patterns in the codebase?"
Answers: "Where are the N+1 queries, memory leaks, and blocking calls?"
Answers: "Which components re-render unnecessarily or import too much?"

Architecture:
- Pattern-based detection: regex patterns for known anti-patterns
- Context-aware scanning: skip test files, downgrade dev-only code
- AST-pattern heuristics: detect loop+DB combos, render misuses, etc.
- Multi-phase: file discovery → per-file scan → dedup → stats → risk

Performance Hint Categories (by severity):
- critical:  n_plus_one, sync_blocking
- high:      memory_leak, expensive_renders
- medium:    large_bundle, inefficient_iteration
- low:       unoptimized_images, cache_miss

Each finding includes a hint, detail, and fix_suggestion to guide
developers toward the optimal fix.
"""

import os
import re
import signal
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

# ─── Safety Limits ────────────────────────────────────────────

MAX_FILE_SIZE = 200 * 1024  # 200KB — skip files larger than this to avoid slow regex
MAX_FILES_TO_SCAN = 5000      # Max files to scan (prevents timeout on huge repos)
PER_REGEX_TIMEOUT_SEC = 2    # Max seconds per single regex.finditer call
PER_FILE_TIMEOUT_SEC = 5     # Max seconds per file across all patterns
MAX_MATCHES_PER_PATTERN = 50  # Cap matches per pattern per file to prevent runaway results
MAX_TOTAL_FINDINGS = 500      # Cap total findings to prevent explosion
WIDE_QUANT_TRUNCATION = 15000  # Truncate content to this size for patterns with wide quantifiers

# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".html", ".vue", ".svelte",
}

# File extensions that are primarily frontend / markup (for category-specific scans)
FRONTEND_EXTENSIONS = {".jsx", ".tsx", ".vue", ".svelte", ".html"}
BACKEND_EXTENSIONS = {".py", ".rs", ".go"}
JS_TS_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}

# Test directory / file indicators
TEST_INDICATORS = [
    '.test.', '.spec.', '__tests__', 'test/', 'tests/',
    'spec/', 'specs/', 'fixtures/', '__mocks__',
    '.stories.', '.story.',
]

# ─── Performance Hint Pattern Definitions ──────────────────────

PERF_HINT_CATEGORIES = {
    # ── N+1 Query ──────────────────────────────────────────────
    "n_plus_one": {
        "severity": "critical",
        "category": "n_plus_one",
        "description": "Sequential DB queries inside loops — potential N+1 query problem",
        "patterns": [
            # JS/TS: .find() / .findOne() / .query() / .execute() inside for/while/forEach
            {
                "regex": (
                    r'(?:for\s*\(|while\s*\(|\.forEach\s*\()'
                    r'[^}]{0,80}?'
                    r'\.(?:find|findOne|findById|query|execute|raw|sql|createQuery)\s*\('
                ),
                "hint": "Sequential DB query inside loop — potential N+1 query problem",
                "fix_suggestion": "Use a batch query (e.g. .find({ _id: { $in: ids } })) or DataLoader to coalesce lookups.",
            },
            # Python: ORM queries inside for/while (Django objects.filter/get, SQLAlchemy .query/.execute)
            {
                "regex": (
                    r'(?:for\s+\w+\s+in\s+|while\s+)'
                    r'[^\n]{0,80}?'
                    r'(?:'
                    r'objects\.(?:filter|get|select_related|prefetch_related|all|exclude|annotate|aggregate)\s*\('
                    r'|\.query\s*\.\s*(?:filter|get|all|join|filter_by)\s*\('
                    r'|session\.(?:execute|query|run)\s*\('
                    r'|db\.(?:execute|query|fetch|fetchone|fetchall)\s*\('
                    r'|cursor\.(?:execute|fetchone|fetchall)\s*\('
                    r')'
                ),
                "hint": "ORM query inside loop — potential N+1 query problem",
                "fix_suggestion": "Use .filter(id__in=ids) or prefetch_related() / select_related() for batch loading.",
            },
            # v5.9: Python generic _fetch_* / _get_* helper calls inside loops
            # This catches patterns like: for uid in ids: user = _fetch_user(uid)
            {
                "regex": (
                    r'(?:for\s+\w+\s+in\s+)'
                    r'[^\n]{0,80}?'
                    r'(?:_fetch_|_get_|_load_|_query_|_find_)\w+\s*\(\s*\w+'
                ),
                "hint": "Per-item fetch call inside loop — likely N+1 query pattern",
                "fix_suggestion": "Batch the fetch operation outside the loop, or use a bulk query with .filter(id__in=ids).",
            },
            # Knex / Sequelize / TypeORM in loops
            {
                "regex": (
                    r'(?:for\s*\(|while\s*\(|\.forEach\s*\()'
                    r'[^}]{0,80}?'
                    r'(?:knex|sequelize|getRepository|createQueryBuilder|Model\.)'
                    r'[^;]{0,60}?\.(?:select|where|from|find|query)\s*\('
                ),
                "hint": "Query builder call inside loop — potential N+1 query problem",
                "fix_suggestion": "Move the query builder outside the loop, use IN-clause or a DataLoader pattern.",
            },
        ],
    },

    # ── Expensive Renders ──────────────────────────────────────
    "expensive_renders": {
        "severity": "high",
        "category": "expensive_renders",
        "description": "React components that re-render unnecessarily",
        "patterns": [
            # Inline object/function in JSX props
            {
                "regex": r'<[A-Z]\w+\s[^>]*?(?:style=\{\{[^}]*\}\}|onClick=\{(?:\(\)\s*=>|function))',
                "hint": "Inline object or arrow function in JSX prop causes re-renders on every parent render",
                "fix_suggestion": "Extract the style/onClick to a const or useCallback/useMemo outside the JSX.",
            },
            # setState inside render / componentDidMount without condition
            {
                "regex": r'(?:render\s*\(\s*\)|componentDidMount\s*\(\s*\))[^{]*\{[^}]*?this\.setState\s*\(',
                "hint": "setState in render or componentDidMount without guard — can cause infinite re-render loops",
                "fix_suggestion": "Move setState to an event handler or useEffect with proper dependency array / condition.",
            },
            # useEffect without dependency array (runs every render)
            {
                "regex": r'useEffect\s*\(\s*\(\)\s*=>\s*\{[^}]*\}\s*\)',
                "hint": "useEffect without dependency array runs on every render",
                "fix_suggestion": "Add a dependency array: useEffect(() => {...}, [deps]).",
            },
            # Large component without React.memo export
            # v6: Only match EXPORTED components — internal helpers don't need memo
            {
                "regex": r'export\s+(?:default\s+)?(?:function|const)\s+[A-Z]\w+\s*(?:=\s*\(|\()\s*(?:props|{)',
                "negative_regex": r'React\.memo|memo\(',
                "negative_scope": "file",
                "hint": "Exported component is not wrapped in React.memo — may re-render even when props are unchanged",
                "fix_suggestion": "Wrap the component export with React.memo() if props are shallow-comparable. Note: React.memo is not always beneficial — only use when props are shallow-comparable and the component is expensive to re-render.",
            },
        ],
    },

    # ── Large Bundle ───────────────────────────────────────────
    "large_bundle": {
        "severity": "medium",
        "category": "large_bundle",
        "description": "Large or tree-shake-hostile imports that bloat bundle size",
        "patterns": [
            # import * from
            {
                "regex": r'import\s+\*\s+as\s+\w+\s+from\s+["\'][^"\']+["\']',
                "hint": "Wildcard import (import *) prevents tree-shaking — entire module is bundled",
                "fix_suggestion": "Import only what you need: import { specific } from 'module'.",
            },
            # importing entire lodash (not lodash-es)
            {
                "regex": r'import\s+(?:\w+\s+from\s+)?["\']lodash["\']',
                "hint": "Importing entire lodash (~72KB gzipped) — use lodash-es or per-function imports",
                "fix_suggestion": "Use: import debounce from 'lodash/debounce' or import { debounce } from 'lodash-es'.",
            },
            # importing moment (instead of dayjs/date-fns)
            {
                "regex": r'import\s+(?:\w+\s+from\s+)?["\']moment["\']',
                "hint": "Importing moment.js (~67KB gzipped) — consider dayjs or date-fns for smaller bundles",
                "fix_suggestion": "Replace with: import dayjs from 'dayjs' or import { format } from 'date-fns'.",
            },
            # barrel file re-exports (export * from)
            {
                "regex": r'export\s+\*\s+from\s+["\'][^"\']+["\']',
                "hint": "Barrel file re-export (export *) can hinder tree-shaking across packages",
                "fix_suggestion": "Use explicit named re-exports: export { foo, bar } from './module'.",
            },
            # require('lodash') in Node
            {
                "regex": r'require\s*\(\s*["\']lodash["\']\s*\)',
                "hint": "Requiring entire lodash library — use per-function require('lodash/debounce')",
                "fix_suggestion": "Use: const debounce = require('lodash/debounce') to import only what you need.",
            },
        ],
    },

    # ── Sync Blocking ──────────────────────────────────────────
    "sync_blocking": {
        "severity": "critical",
        "category": "sync_blocking",
        "description": "Synchronous blocking operations in async/request contexts",
        "patterns": [
            # fs.readFileSync / fs.writeFileSync inside route handlers
            {
                "regex": (
                    r'(?:app\.(?:get|post|put|delete|patch)|router\.(?:get|post|put|delete|patch)|'
                    r'server\.(?:get|post|put|delete|patch))'
                    r'[^}]{0,150}?'
                    r'fs\.(?:readFileSync|writeFileSync|appendFileSync|unlinkSync|existsSync|'
                    r'readdirSync|statSync|mkdirSync|rmSync)'
                ),
                "hint": "Synchronous filesystem call in route handler — blocks the event loop",
                "fix_suggestion": "Use fs.promises.readFile / fs.readFile with callbacks, or use async/await with fs/promises.",
            },
            # XMLHttpRequest with sync flag
            {
                "regex": r'new\s+XMLHttpRequest\s*\([^)]*\)[^;]{0,200}?\.open\s*\(\s*["\'](?:GET|POST|PUT|DELETE)["\']\s*,\s*[^,]+,\s*false\s*\)',
                "hint": "Synchronous XMLHttpRequest — blocks the main thread",
                "fix_suggestion": "Use fetch() or XMLHttpRequest with async (true) flag. Synchronous XHR is deprecated.",
            },
            # subprocess.call / subprocess.run (without timeout) in Flask/Django handlers
            {
                "regex": (
                    r'@(?:app|router)\.(?:route|get|post|put|delete|patch)\s*\([^)]*\)'
                    r'[^}]{0,150}?'
                    r'subprocess\.(?:call|run|check_output|check_call)\s*\('
                ),
                "hint": "Subprocess call inside request handler — blocks the worker thread",
                "fix_suggestion": "Use asyncio.create_subprocess_exec() or move to a background task (Celery, RQ).",
            },
            # Python: open().read() inside a route (sync I/O)
            {
                "regex": (
                    r'@(?:app|blueprint)\.(?:route|get|post|put|delete)\s*\([^)]*\)'
                    r'[^}]{0,150}?'
                    r'open\s*\([^)]+\)\.read\s*\(\s*\)'
                ),
                "hint": "Synchronous file read in route handler — blocks the worker thread",
                "fix_suggestion": "Use aiofiles for async file I/O or offload to a background task.",
            },
            # Python: requests.get/post (blocking HTTP) in handler
            {
                "regex": (
                    r'@(?:app|blueprint)\.(?:route|get|post|put|delete)\s*\([^)]*\)'
                    r'[^}]{0,150}?'
                    r'requests\.(?:get|post|put|delete|patch|head)\s*\('
                ),
                "hint": "Blocking HTTP request (requests library) in route handler — stalls the worker",
                "fix_suggestion": "Use httpx.AsyncClient or aiohttp for async HTTP, or offload to a background task.",
            },
            # v5.9: Python time.sleep() inside async function — blocks the event loop
            {
                "regex": r'async\s+def\s+\w+[^}]{0,500}?time\.sleep\s*\(',
                "hint": "time.sleep() inside async function — blocks the entire event loop",
                "fix_suggestion": "Use asyncio.sleep() instead of time.sleep() in async functions to avoid blocking the event loop.",
            },
            # v5.9: Python requests.get/post inside async function — blocking HTTP in async
            {
                "regex": r'async\s+def\s+\w+[^}]{0,500}?requests\.(?:get|post|put|delete|patch|head)\s*\(',
                "hint": "Blocking requests.get/post inside async function — stalls the event loop",
                "fix_suggestion": "Use httpx.AsyncClient or aiohttp for async HTTP requests inside async functions.",
            },
            # v5.9: Python subprocess in async function without asyncio
            {
                "regex": r'async\s+def\s+\w+[^}]{0,500}?subprocess\.(?:call|run|check_output|check_call)\s*\(',
                "hint": "Blocking subprocess call inside async function — stalls the event loop",
                "fix_suggestion": "Use asyncio.create_subprocess_exec() for non-blocking subprocess calls in async functions.",
            },
        ],
    },

    # ── Memory Leak ────────────────────────────────────────────
    "memory_leak": {
        "severity": "high",
        "category": "memory_leak",
        "description": "Event listeners or intervals that are never cleaned up",
        "patterns": [
            # addEventListener without matching removeEventListener
            {
                "regex": r'\.addEventListener\s*\(\s*["\'](\w+)["\']',
                "negative_regex": r'\.removeEventListener\s*\(\s*["\']\1["\']',
                "hint": "addEventListener without corresponding removeEventListener — potential memory leak",
                "fix_suggestion": "Store the handler reference and call removeEventListener in the cleanup phase (useEffect return / componentWillUnmount).",
            },
            # setInterval without clearInterval
            {
                "regex": r'(?:const|let|var)?\s*\w*\s*=\s*setInterval\s*\(',
                "negative_regex": r'clearInterval\s*\(',
                "hint": "setInterval without clearInterval — interval runs forever, causing memory/CPU leak",
                "fix_suggestion": "Store the interval ID and call clearInterval() in the cleanup phase (useEffect return / componentWillUnmount).",
            },
            # setTimeout without clearTimeout (less severe but still a leak source)
            {
                "regex": r'(?:const|let|var)?\s*\w*\s*=\s*setTimeout\s*\(',
                "negative_regex": r'clearTimeout\s*\(',
                "hint": "setTimeout assigned but no clearTimeout seen — timeout may fire after component unmounts",
                "fix_suggestion": "Store the timeout ID and call clearTimeout() in the cleanup phase to prevent stale updates.",
            },
            # Closures retaining large objects (heuristic: large buffer assigned then used in closure)
            {
                "regex": r'(?:const|let|var)\s+\w+\s*=\s*(?:new\s+(?:Array|Buffer|Uint8Array)|Array\s*\(\s*\d{4,}\s*\)|Buffer\.alloc\s*\(\s*\d{5,})',
                "hint": "Large buffer/array allocation — ensure it is not captured by a long-lived closure",
                "fix_suggestion": "Null out the reference after use, or use a WeakRef / scoped allocator to allow GC.",
            },
            # EventEmitter .on() without .off() or .removeListener()
            {
                "regex": r'\.(?:on|addListener)\s*\(\s*["\'](\w+)["\']',
                "negative_regex": r'\.(?:off|removeListener|removeAllListeners)\s*\(\s*["\']\1["\']',
                "hint": "EventEmitter .on() without matching .off() — listener accumulates over time",
                "fix_suggestion": "Call .off() or .removeListener() when the subscriber is done (e.g., in cleanup / destructor).",
            },
        ],
    },

    # ── Inefficient Iteration ──────────────────────────────────
    "inefficient_iteration": {
        "severity": "medium",
        "category": "inefficient_iteration",
        "description": "Multi-pass iterations, nested loops, or unmemoized recursion",
        "patterns": [
            # .map().filter().reduce() chain — multi-pass over array
            {
                "regex": r'\.map\s*\([^)]+\)\s*\.filter\s*\([^)]+\)\s*\.reduce\s*\(',
                "hint": "Chained .map().filter().reduce() — iterates the array 3 times; can be single-pass",
                "fix_suggestion": "Use a single .reduce() that maps, filters, and accumulates in one pass.",
            },
            # .filter().map() — two passes
            {
                "regex": r'\.filter\s*\([^)]+\)\s*\.map\s*\(',
                "hint": "Chained .filter().map() — iterates the array twice; can be single-pass",
                "fix_suggestion": "Use a single .reduce() or .flatMap() to filter and transform in one pass.",
            },
            # Nested for/while loops (O(n²) heuristic)
            {
                "regex": r'(?:for\s*\(|while\s*\()(?:[^{]*\{[^}]*){1,3}(?:for\s*\(|while\s*\()',
                "hint": "Nested loops detected — potential O(n²) complexity with large datasets",
                "fix_suggestion": "Consider using a Map/Set for O(1) lookups, or restructure with a hash map to avoid the inner loop.",
            },
            # Recursive function without memoization (heuristic: recursive calls with same args pattern)
            {
                "regex": r'(?:function|const|def)\s+(\w+)[^=]*?(?:=|\s)\s*(?:\([^)]*\)\s*=>|function\s*\(|def\s+\1)',
                "self_call_regex": True,  # Flag: check if function calls itself
                "hint": "Recursive function without memoization — may recompute identical sub-problems",
                "fix_suggestion": "Add memoization (functools.lru_cache, or a custom cache Map) to avoid redundant computation.",
            },
            # v5.9: Python string concatenation in loop (result += ...) — O(n²) pattern
            {
                "regex": r'(?:for\s+\w+\s+in\s+|while\s+)[^\n]{0,80}?result\s*\+=\s*(?:str\s*\()?[\w.\[\]]+',
                "hint": "String concatenation inside loop using += — O(n²) time complexity",
                "fix_suggestion": "Use list.append() + ''.join() for O(n) string building instead of repeated concatenation.",
            },
            # v5.9: Python list.append in loop (suggest list comprehension)
            {
                "regex": r'(?:for\s+\w+\s+in\s+)range\s*\([^)]+\):\s*\n\s*(?:result|items|output)\s*\.\s*append\s*\(',
                "hint": "list.append() inside for-range loop — list comprehension is faster and more Pythonic",
                "fix_suggestion": "Replace with a list comprehension: [expression for i in range(n)]",
            },
        ],
    },

    # ── Unoptimized Images ─────────────────────────────────────
    "unoptimized_images": {
        "severity": "low",
        "category": "unoptimized_images",
        "description": "Image tags missing lazy loading, dimensions, or modern formats",
        "patterns": [
            # <img> without width/height
            {
                "regex": r'<img\s[^>]*?src=["\'][^"\']*["\'][^>]*?>',
                "negative_regex": r'width\s*=|height\s*=',
                "hint": "<img> tag without width/height — causes layout shift (CLS) when image loads",
                "fix_suggestion": "Add width and height attributes (or aspect-ratio CSS) to reserve space and reduce CLS.",
            },
            # <img> without loading="lazy"
            {
                "regex": r'<img\s[^>]*?src=["\'][^"\']*["\'][^>]*?>',
                "negative_regex": r'loading\s*=\s*["\']lazy["\']',
                "hint": '<img> tag without loading="lazy" — eagerly loads off-screen images',
                "fix_suggestion": 'Add loading="lazy" to defer off-screen image loading and reduce initial page weight.',
            },
            # <img> with unoptimized format (.png for photos, .bmp, .tiff)
            {
                "regex": r'<img\s[^>]*?src=["\'][^"\']*\.(?:png|bmp|tiff|tif)["\'][^>]*?>',
                "hint": "Image using unoptimized format (PNG/BMP/TIFF) — consider WebP or AVIF",
                "fix_suggestion": "Convert to WebP (30-50% smaller) or AVIF (50-80% smaller) with <picture> fallback.",
            },
            # Next.js <Image> without priority on LCP candidate
            {
                "regex": r'<Image\s[^>]*?src=["\'][^"\']*["\'][^>]*?>',
                "negative_regex": r'priority',
                "hint": "Next.js <Image> without priority — LCP image may load late",
                "fix_suggestion": "Add priority prop to the above-the-fold <Image> component for LCP optimization.",
            },
        ],
    },

    # ── Cache Miss ─────────────────────────────────────────────
    "cache_miss": {
        "severity": "low",
        "category": "cache_miss",
        "description": "Repeated expensive computations without caching or memoization",
        "patterns": [
            # Repeated fetch/axios calls to same endpoint (heuristic: identical URL strings)
            {
                "regex": r'(?:fetch|axios\.(?:get|post|put|delete))\s*\(\s*["\']([^"\']+)["\']',
                "duplicate_check": True,  # Flag: check for duplicate URLs across the file
                "hint": "Repeated API call to the same endpoint — consider caching the response",
                "fix_suggestion": "Use SWR, React Query, or a simple cache (Map with TTL) to avoid duplicate network requests.",
            },
            # Expensive computation function without memoization
            {
                "regex": r'(?:function|const)\s+(?:compute|calculate|process|transform|parse|format|generate)\w*\s*(?:=\s*(?:\([^)]*\)\s*=>|function\s*\())',
                "hint": "Computation function without memoization — re-runs on every call with same inputs",
                "fix_suggestion": "Wrap with useMemo (React), memoizee, or functools.lru_cache to cache results for repeated inputs.",
            },
            # No ETag / If-Modified-Since header handling in API responses
            {
                "regex": r'(?:app|router)\.(?:get|all)\s*\(\s*["\'][^"\']+["\'][^}]{0,200}?(?:res\.(?:json|send|end))',
                "negative_regex": r'(?:ETag|etag|If-Modified-Since|Cache-Control|cache-control|stale-while-revalidate)',
                "hint": "API response without caching headers (ETag, Cache-Control) — clients re-fetch unchanged data",
                "fix_suggestion": "Add ETag, Cache-Control, or Last-Modified headers to enable conditional requests.",
            },
            # Python: repeated DB query in view without caching
            {
                "regex": r'(?:Model|objects)\.(?:filter|get|all|select_related|prefetch_related)\s*\([^)]*\)',
                "negative_regex": r'(?:cache_page|@cache|lru_cache|cache\.get|redis\.get)',
                "hint": "DB query in view without caching — hits the database on every request",
                "fix_suggestion": "Add @cache_page (Django) or @lru_cache / Redis caching to avoid repeated DB hits.",
            },
        ],
    },
}

# ─── Main Detection Function ──────────────────────────────────

def detect_perf_hints(
    workspace: str,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = MAX_FILES_TO_SCAN
) -> Dict[str, Any]:
    """
    Detect performance anti-patterns and optimization opportunities in source code.

    Scans source files for known performance anti-patterns across 8 categories.
    Context-aware: skips test files, downgrades findings in dev-only code.

    Args:
        workspace: Absolute path to workspace
        severity: Optional filter: "critical", "high", "medium", "low"
        category: Optional filter: "n_plus_one", "sync_blocking", "memory_leak",
                  "expensive_renders", "large_bundle", "inefficient_iteration",
                  "unoptimized_images", "cache_miss"
        config: CodeLens config dict (optional overrides)
        max_files: Maximum number of files to scan (default 5000, use 0 for unlimited)

    Returns:
        Dict with findings, stats, risk level, and recommendations
    """
    workspace = os.path.abspath(workspace)

    # Merge config overrides
    ignore_dirs = DEFAULT_IGNORE_DIRS
    if config and "ignore_dirs" in config:
        ignore_dirs = DEFAULT_IGNORE_DIRS | set(config["ignore_dirs"])

    findings: List[Dict[str, Any]] = []
    files_scanned = 0
    truncated = False

    # Categories to scan (apply filter early)
    categories_to_scan = PERF_HINT_CATEGORIES
    if category:
        if category in PERF_HINT_CATEGORIES:
            categories_to_scan = {category: PERF_HINT_CATEGORIES[category]}
        else:
            return {
                "status": "ok",
                "workspace": workspace,
                "severity_filter": severity,
                "category_filter": category,
                "stats": {
                    "total_hints": 0,
                    "by_category": {},
                    "by_severity": {},
                    "files_scanned": 0,
                },
                "risk": "none",
                "findings": [],
                "recommendations": [f"Unknown category '{category}'. Valid: {', '.join(sorted(PERF_HINT_CATEGORIES.keys()))}"],
            }

    # ─── Phase 1: File discovery & per-file scanning ─────────
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            # Honor max_files limit
            if max_files and max_files > 0 and files_scanned >= max_files:
                truncated = True
                break

            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    files_scanned += 1
                    continue
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # Skip test files (lower-severity scan)
            is_test = _is_test_file(rel_path)

            # Scan for all categories relevant to this file type
            file_start = time.monotonic()
            file_findings = _scan_file_hints(
                content, rel_path, ext, is_test, categories_to_scan,
                file_start_time=file_start
            )
            findings.extend(file_findings)

            # Check if we've hit file or finding limits
            if files_scanned >= MAX_FILES_TO_SCAN:
                truncated = True
                break
            if len(findings) >= MAX_TOTAL_FINDINGS:
                truncated = True
                break

        if truncated:
            break

    # ─── Phase 2: Cross-file analyses ─────────────────────────
    # (duplicate API URLs, etc. — done per-file already, but we
    #  could extend here for workspace-wide duplicate detection)

    # ─── Truncate findings if over cap ──────────────────────────
    if len(findings) > MAX_TOTAL_FINDINGS:
        findings = findings[:MAX_TOTAL_FINDINGS]
        truncated = True

    # ─── Deduplicate findings ─────────────────────────────────
    findings = _deduplicate_findings(findings)

    # v6: Per-category cap — if a single category dominates the findings,
    # emit a summary instead of overwhelming the output.
    MAX_PER_CATEGORY = 100
    category_counts = {}
    capped_findings = []
    category_overflow = {}
    for f in findings:
        cat = f.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        if category_counts[cat] <= MAX_PER_CATEGORY:
            capped_findings.append(f)
        else:
            category_overflow[cat] = category_overflow.get(cat, 0) + 1
    findings = capped_findings

    # ─── Apply severity filter ────────────────────────────────
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]

    # ─── Compute stats ────────────────────────────────────────
    stats = _compute_stats(findings, files_scanned)
    stats["truncated"] = truncated

    # ─── Compute risk ─────────────────────────────────────────
    risk = _compute_risk(findings)

    # ─── Detect frameworks for adaptive recommendations ──────
    detected_frameworks = _detect_frameworks_lightweight(workspace)

    # ─── Generate recommendations ─────────────────────────────
    recommendations = _generate_recommendations(findings, stats, detected_frameworks)

    return {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "category_filter": category,
        "stats": {**stats, "truncated_categories": category_overflow if category_overflow else None},
        "risk": risk,
        "frameworks_detected": detected_frameworks,
        "hints": findings[:200],  # Cap to avoid explosion (key matches stats.total_hints)
        "recommendations": recommendations,
    }

# ─── Per-file Hint Scanner ─────────────────────────────────────

def _scan_file_hints(
    content: str,
    rel_path: str,
    ext: str,
    is_test: bool,
    categories: Dict[str, Dict[str, Any]],
    file_start_time: Optional[float] = None
) -> List[Dict[str, Any]]:
    """Scan a single file's content for performance anti-patterns."""
    findings: List[Dict[str, Any]] = []

    for cat_name, cat_def in categories.items():
        # Category-level extension gating
        if not _category_applies_to_file(cat_name, ext):
            continue

        for pattern_def in cat_def["patterns"]:
            # Per-file timeout: skip remaining patterns if file is taking too long
            if file_start_time is not None:
                elapsed = time.monotonic() - file_start_time
                if elapsed > PER_FILE_TIMEOUT_SEC:
                    logger.debug(f"Per-file timeout ({PER_FILE_TIMEOUT_SEC}s) reached for {rel_path}, skipping remaining patterns")
                    return findings
            # Handle special pattern types
            if pattern_def.get("self_call_regex"):
                # Recursive function detection: find function defs that call themselves
                sub_findings = _detect_recursive_functions(
                    content, rel_path, cat_def, pattern_def
                )
                findings.extend(sub_findings)
                continue

            if pattern_def.get("duplicate_check"):
                # Duplicate API URL detection
                sub_findings = _detect_duplicate_api_calls(
                    content, rel_path, cat_def, pattern_def
                )
                findings.extend(sub_findings)
                continue

            regex = pattern_def["regex"]
            negative_regex = pattern_def.get("negative_regex")

            # Truncate content for regex patterns with wide quantifiers
            # to prevent catastrophic backtracking on large files.
            # Patterns with {0,N} or .*? are the main risk.
            scan_content = content
            if len(content) > WIDE_QUANT_TRUNCATION and _has_wide_quantifier(regex):
                scan_content = content[:WIDE_QUANT_TRUNCATION]

            try:
                # Use a timeout to prevent catastrophic backtracking
                matches = _timed_finditer(regex, scan_content)
                if matches is None:
                    # Timed out — skip this pattern for this file
                    continue

                for match_idx, match in enumerate(matches):
                    if match_idx >= MAX_MATCHES_PER_PATTERN:
                        break
                    line_num = content[:match.start()].count('\n') + 1

                    # Apply negative regex: if the negative pattern exists in the
                    # matched region, skip this match.
                    if negative_regex:
                        # v6: Check scope for negative regex
                        # 'file' scope = check entire file content (for patterns like memo)
                        # default = check ~20-line window around the match
                        neg_scope = pattern_def.get('negative_scope', 'window')
                        if neg_scope == 'file':
                            context_window = content
                        else:
                            context_start = max(0, match.start() - 2000)
                            context_end = min(len(content), match.end() + 2000)
                            context_window = content[context_start:context_end]

                        # For backreference patterns like \1, we need to resolve them
                        resolved_neg = negative_regex
                        if match.lastindex and match.lastindex >= 1:
                            resolved_neg = negative_regex.replace(r'\1', re.escape(match.group(1)))

                        if re.search(resolved_neg, context_window, re.DOTALL):
                            continue

                    severity = cat_def["severity"]

                    # Downgrade severity for test files
                    if is_test:
                        severity = _downgrade_severity(severity)

                    findings.append({
                        "type": "performance_hint",
                        "category": cat_def["category"],
                        "severity": severity,
                        "file": rel_path,
                        "line": line_num,
                        "hint": pattern_def["hint"],
                        "detail": (
                            f"{_extract_matched_summary(match)} at line {line_num} in {rel_path}. "
                            f"{cat_def['description']}."
                        ),
                        "fix_suggestion": pattern_def["fix_suggestion"],
                    })

            except re.error:
                continue

    return findings

def _detect_recursive_functions(
    content: str,
    rel_path: str,
    cat_def: Dict[str, Any],
    pattern_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Detect recursive functions that lack memoization.

    Finds function definitions, then checks if they call themselves.
    """
    findings: List[Dict[str, Any]] = []

    # Match function definitions and capture the function name
    func_pattern = r'(?:function|const|let|var|def)\s+(\w+)'
    for func_match in re.finditer(func_pattern, content):
        func_name = func_match.group(1)

        # Skip obvious non-computation functions
        if not re.match(r'(?i)(?:compute|calculate|process|transform|parse|format|generate|fibonacci|factorial|fib|fact)', func_name):
            continue

        # Check if the function body contains a self-call
        # Find the function body approximately (from match to next function or EOF)
        func_start = func_match.start()
        # Find the end of the line where the function is defined
        line_end = content.find('\n', func_start)
        if line_end == -1:
            line_end = len(content)

        # Get a reasonable chunk of the function body (next ~50 lines)
        chunk_end = min(len(content), func_start + 3000)
        func_body = content[func_start:chunk_end]

        # Check for self-call: func_name(...) in the body (but not the definition line)
        definition_line = content[:line_end]
        body_after_def = content[line_end:chunk_end]

        self_call_pattern = rf'\b{re.escape(func_name)}\s*\('
        if re.search(self_call_pattern, body_after_def):
            # Check if there's any caching/memoization
            has_cache = bool(re.search(
                r'(?:memo|cache|lru_cache|functools\.lru_cache|useMemo|memoize)',
                func_body
            ))

            if not has_cache:
                line_num = content[:func_match.start()].count('\n') + 1
                findings.append({
                    "type": "performance_hint",
                    "category": cat_def["category"],
                    "severity": cat_def["severity"],
                    "file": rel_path,
                    "line": line_num,
                    "hint": pattern_def["hint"],
                    "detail": (
                        f"Recursive function '{func_name}' at line {line_num} in {rel_path} "
                        f"has no memoization — may recompute identical sub-problems."
                    ),
                    "fix_suggestion": pattern_def["fix_suggestion"],
                })

    return findings

def _detect_duplicate_api_calls(
    content: str,
    rel_path: str,
    cat_def: Dict[str, Any],
    pattern_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Detect duplicate API calls to the same endpoint within a file."""
    findings: List[Dict[str, Any]] = []

    regex = pattern_def["regex"]
    url_map: Dict[str, List[int]] = defaultdict(list)  # url -> [line_numbers]

    for match in re.finditer(regex, content):
        if match.lastindex and match.lastindex >= 1:
            url = match.group(1)
        else:
            continue

        line_num = content[:match.start()].count('\n') + 1
        url_map[url].append(line_num)

    # Report URLs that are called more than once
    for url, lines in url_map.items():
        if len(lines) > 1:
            severity = cat_def["severity"]
            if _is_test_file(rel_path):
                severity = _downgrade_severity(severity)

            findings.append({
                "type": "performance_hint",
                "category": cat_def["category"],
                "severity": severity,
                "file": rel_path,
                "line": lines[0],
                "hint": pattern_def["hint"],
                "detail": (
                    f"API endpoint '{_truncate_url(url)}' called {len(lines)} times "
                    f"(lines {', '.join(str(l) for l in lines)}) in {rel_path}. "
                    f"Consider caching the response."
                ),
                "fix_suggestion": pattern_def["fix_suggestion"],
            })

    return findings

# ─── Category-File Relevance ───────────────────────────────────

def _category_applies_to_file(category: str, ext: str, rel_path: str = "") -> bool:
    """Determine if a performance hint category is relevant to a file extension.

    Avoids scanning irrelevant file types (e.g., no n_plus_one in .html files).
    """
    # Categories that apply to all source files
    universal = {"inefficient_iteration", "cache_miss"}
    if category in universal:
        # v5.9: HTML template files should not be scanned for inefficient_iteration.
        # Jinja2/Django template {% for %} loops are server-rendered template
        # iteration, not JavaScript/Python runtime performance issues.
        if category == "inefficient_iteration" and ext in {".html", ".htm", ".jinja", ".jinja2", ".djt"}:
            return False
        # v5.9: Also skip Vue/Svelte template sections — they use v-for/{#each}
        # which are compile-time directives, not runtime loops.
        if category == "inefficient_iteration" and ext in {".vue", ".svelte"}:
            return False
        return True

    # Frontend-specific categories
    frontend_only = {"expensive_renders", "unoptimized_images"}
    if category in frontend_only:
        return ext in FRONTEND_EXTENSIONS or ext in JS_TS_EXTENSIONS

    # Backend-heavy categories (also relevant in JS/TS backend code)
    backend_heavy = {"sync_blocking", "n_plus_one"}
    if category in backend_heavy:
        return ext in JS_TS_EXTENSIONS or ext in BACKEND_EXTENSIONS

    # Large bundle: JS/TS only
    if category == "large_bundle":
        return ext in JS_TS_EXTENSIONS

    # Memory leak: JS/TS + Python
    if category == "memory_leak":
        return ext in JS_TS_EXTENSIONS or ext == ".py"

    # Default: allow for known source extensions
    return ext in SOURCE_EXTENSIONS

# ─── Helper Functions ──────────────────────────────────────────

def _is_test_file(rel_path: str) -> bool:
    """Check if a file is in a test directory or is a test file."""
    return any(indicator in rel_path for indicator in TEST_INDICATORS)

def _downgrade_severity(severity: str) -> str:
    """Downgrade severity by one level (for test files / dev-only code)."""
    downgrade = {
        "critical": "high",
        "high": "medium",
        "medium": "low",
        "low": "low",  # Can't go lower
    }
    return downgrade.get(severity, severity)

def _extract_matched_summary(match: re.Match) -> str:
    """Extract a short summary of the match for the detail field."""
    matched_text = match.group(0)
    # Truncate long matches
    if len(matched_text) > 80:
        return matched_text[:77] + "..."
    return matched_text

def _truncate_url(url: str) -> str:
    """Truncate long URLs for display in findings."""
    if len(url) > 60:
        return url[:57] + "..."
    return url

def _deduplicate_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate findings (same file, line, category, hint)."""
    seen: Set[Tuple[str, int, str, str]] = set()
    unique = []

    for finding in findings:
        key = (
            finding.get("file", ""),
            finding.get("line", 0),
            finding.get("category", ""),
            finding.get("hint", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique

# ─── Stats & Risk Computation ──────────────────────────────────

def _compute_stats(
    findings: List[Dict[str, Any]],
    files_scanned: int
) -> Dict[str, Any]:
    """Compute statistics from findings."""
    by_category: Dict[str, int] = defaultdict(int)
    by_severity: Dict[str, int] = defaultdict(int)

    for f in findings:
        by_category[f.get("category", "unknown")] += 1
        by_severity[f.get("severity", "unknown")] += 1

    return {
        "total_hints": len(findings),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "files_scanned": files_scanned,
    }

def _compute_risk(findings: List[Dict[str, Any]]) -> str:
    """Compute overall risk level based on findings.

    Risk escalates with severity and count:
    - critical findings → "critical" risk
    - 3+ high findings → "critical" risk
    - any high findings → "high" risk
    - any medium findings → "medium" risk
    - only low findings → "low" risk
    - no findings → "none" risk
    """
    if not findings:
        return "none"

    by_severity: Dict[str, int] = defaultdict(int)
    for f in findings:
        by_severity[f.get("severity", "low")] += 1

    if by_severity.get("critical", 0) > 0:
        return "critical"
    if by_severity.get("high", 0) >= 3:
        return "critical"
    if by_severity.get("high", 0) > 0:
        return "high"
    if by_severity.get("medium", 0) > 0:
        return "medium"

    return "low"

# ─── Recommendations ───────────────────────────────────────────

def _detect_frameworks_lightweight(workspace: str) -> List[str]:
    """Lightweight framework detection for adaptive recommendations.

    Only checks package.json and file patterns — does NOT import the
    heavy framework_detect module to keep perf-hint fast.
    """
    frameworks = []
    pkg_path = os.path.join(workspace, "package.json")
    deps = {}
    if os.path.exists(pkg_path):
        try:
            import json
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            deps.update(pkg.get("dependencies", {}))
            deps.update(pkg.get("devDependencies", {}))
        except (json.JSONDecodeError, IOError):
            pass

    # Check frameworks from deps
    if "react" in deps or "react-dom" in deps:
        frameworks.append("react")
    if "next" in deps:
        frameworks.append("next.js")
    if "vue" in deps:
        frameworks.append("vue")
    if "svelte" in deps or "@sveltejs/kit" in deps:
        frameworks.append("svelte")
    if "angular" in deps or "@angular/core" in deps:
        frameworks.append("angular")

    # Check file patterns
    if not frameworks:
        for root, dirs, filenames in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
            if '.codelens' in root:
                dirs.clear()
                continue
            for f in filenames:
                if f.endswith('.svelte') and 'svelte' not in frameworks:
                    frameworks.append("svelte")
                if f.endswith('.vue') and 'vue' not in frameworks:
                    frameworks.append("vue")
            if frameworks:
                break

    return frameworks


def _generate_recommendations(
    findings: List[Dict[str, Any]],
    stats: Dict[str, Any],
    frameworks: Optional[List[str]] = None
) -> List[str]:
    """Generate actionable recommendations based on findings.

    Adapts recommendations to the detected framework (React, Svelte,
    Vue, Angular) instead of always suggesting React-specific fixes.
    """
    recs = []
    frameworks = frameworks or []
    has_react = "react" in frameworks or "next.js" in frameworks
    has_svelte = "svelte" in frameworks
    has_vue = "vue" in frameworks
    has_angular = "angular" in frameworks

    if not findings:
        recs.append("No performance anti-patterns detected. Codebase looks clean!")
        return recs

    by_category = stats.get("by_category", {})

    # ── Critical: N+1 queries ──
    n_plus_one = by_category.get("n_plus_one", 0)
    if n_plus_one:
        recs.append(
            f"N+1 QUERIES: Found {n_plus_one} potential N+1 query pattern(s). "
            f"These are the highest-impact performance issue — each loop iteration "
            f"hits the database individually. Batch queries with $in / IN-clauses "
            f"or use DataLoader / prefetch_related to coalesce lookups."
        )

    # ── Critical: Sync blocking ──
    sync_blocking = by_category.get("sync_blocking", 0)
    if sync_blocking:
        recs.append(
            f"SYNC BLOCKING: Found {sync_blocking} synchronous blocking call(s) in request handlers. "
            f"These block the event loop / worker thread, causing cascading latency. "
            f"Replace with async equivalents (fs/promises, httpx, asyncio) or offload to background tasks."
        )

    # ── High: Memory leaks ──
    memory_leak = by_category.get("memory_leak", 0)
    if memory_leak:
        if has_svelte:
            recs.append(
                f"MEMORY LEAKS: Found {memory_leak} potential memory leak(s). "
                f"Missing removeEventListener / clearInterval / clearTimeout causes listeners "
                f"and intervals to accumulate. In Svelte, clean up in the onDestroy() lifecycle "
                f"callback or use the on:destroy event on components."
            )
        elif has_vue:
            recs.append(
                f"MEMORY LEAKS: Found {memory_leak} potential memory leak(s). "
                f"Missing removeEventListener / clearInterval / clearTimeout causes listeners "
                f"and intervals to accumulate. In Vue, clean up in the onUnmounted() composition "
                f"API hook or the beforeUnmount / unmounted options API lifecycle."
            )
        elif has_angular:
            recs.append(
                f"MEMORY LEAKS: Found {memory_leak} potential memory leak(s). "
                f"Missing removeEventListener / clearInterval / clearTimeout causes listeners "
                f"and intervals to accumulate. In Angular, implement OnDestroy and clean up "
                f"in ngOnDestroy(). Consider using takeUntil pattern with RxJS."
            )
        else:
            recs.append(
                f"MEMORY LEAKS: Found {memory_leak} potential memory leak(s). "
                f"Missing removeEventListener / clearInterval / clearTimeout causes listeners "
                f"and intervals to accumulate. Always clean up in useEffect return / componentWillUnmount."
            )

    # ── High: Expensive renders ──
    expensive_renders = by_category.get("expensive_renders", 0)
    if expensive_renders:
        if has_svelte:
            recs.append(
                f"EXPENSIVE RENDERS: Found {expensive_renders} re-render anti-pattern(s). "
                f"In Svelte, reactivity is compile-time — use $: reactive declarations "
                f"instead of manual state updates. Avoid creating new objects/arrays in "
                f"reactive statements. Use the {{#key}} block for conditional re-rendering."
            )
        elif has_vue:
            recs.append(
                f"EXPENSIVE RENDERS: Found {expensive_renders} re-render anti-pattern(s). "
                f"In Vue, use computed() for derived state, v-once for static content, "
                f"and v-memo for conditional re-rendering. Avoid inline objects/functions "
                f"in template props — extract them to reactive() or ref() declarations."
            )
        elif has_angular:
            recs.append(
                f"EXPENSIVE RENDERS: Found {expensive_renders} re-render anti-pattern(s). "
                f"In Angular, use OnPush change detection strategy, trackBy with *ngFor, "
                f"and pure pipes instead of method calls in templates. Consider using "
                f"the async pipe with Observables for efficient data binding."
            )
        else:
            recs.append(
                f"EXPENSIVE RENDERS: Found {expensive_renders} re-render anti-pattern(s). "
                f"Inline objects/functions in JSX props and missing React.memo cause unnecessary "
                f"child re-renders. Extract constants, use useCallback/useMemo, wrap with React.memo."
            )

    # ── Medium: Large bundle ──
    large_bundle = by_category.get("large_bundle", 0)
    if large_bundle:
        recs.append(
            f"LARGE BUNDLE: Found {large_bundle} bundle-bloating import(s). "
            f"Wildcard imports and full-library imports (lodash, moment) prevent tree-shaking. "
            f"Switch to per-function imports or lighter alternatives (lodash-es, dayjs, date-fns)."
        )

    # ── Medium: Inefficient iteration ──
    inefficient = by_category.get("inefficient_iteration", 0)
    if inefficient:
        recs.append(
            f"INEFFICIENT ITERATION: Found {inefficient} suboptimal iteration pattern(s). "
            f"Multi-pass .map().filter().reduce() chains and nested loops waste CPU cycles. "
            f"Use single-pass .reduce() or Map/Set for O(1) lookups."
        )

    # ── Low: Unoptimized images ──
    images = by_category.get("unoptimized_images", 0)
    if images:
        recs.append(
            f"UNOPTIMIZED IMAGES: Found {images} unoptimized <img> tag(s). "
            f"Add loading='lazy', width/height attributes, and convert PNGs to WebP/AVIF "
            f"to reduce page weight and improve Core Web Vitals."
        )

    # ── Low: Cache miss ──
    cache_miss = by_category.get("cache_miss", 0)
    if cache_miss:
        if has_svelte:
            recs.append(
                f"CACHE MISSES: Found {cache_miss} repeated computation without caching. "
                f"Add response caching (ETag, Cache-Control), memoization (lru_cache), "
                f"or use SvelteKit's load function caching and page stores to avoid redundant work."
            )
        elif has_vue:
            recs.append(
                f"CACHE MISSES: Found {cache_miss} repeated computation without caching. "
                f"Add response caching (ETag, Cache-Control), memoization (lru_cache, computed), "
                f"or use Vue's computed() and Pinia getters for derived state caching."
            )
        else:
            recs.append(
                f"CACHE MISSES: Found {cache_miss} repeated computation without caching. "
                f"Add response caching (ETag, Cache-Control), memoization (lru_cache, useMemo), "
                f"or a data-fetching library (SWR, React Query) to avoid redundant work."
            )

    # ── General advice ──
    critical_count = stats.get("by_severity", {}).get("critical", 0)
    if critical_count > 0:
        recs.append(
            f"PRIORITY: Address the {critical_count} critical finding(s) first — "
            f"N+1 queries and sync blocking calls have the largest impact on response times."
        )

    recs.append(
        "GENERAL: Run Lighthouse (web) or py-spy (Python) profiler on real workloads "
        "to validate these hints and find bottlenecks the static analyzer cannot detect."
    )

    return recs


# ─── Regex Safety Helpers ──────────────────────────────────────

# Precompiled check for patterns prone to catastrophic backtracking
_WIDE_QUANTIFIER_RE = re.compile(r'\{0,\d+\}|\.\*\?|\.\+\?')


def _has_wide_quantifier(regex_pattern: str) -> bool:
    """Check if a regex pattern contains wide quantifiers that risk backtracking."""
    return bool(_WIDE_QUANTIFIER_RE.search(regex_pattern))


class _RegexTimeout(Exception):
    """Raised when a regex search exceeds the time limit."""
    pass


def _timed_finditer(pattern: str, content: str, timeout: float = PER_REGEX_TIMEOUT_SEC):
    """
    Run re.finditer with a time limit to prevent catastrophic backtracking.
    Returns list of matches (capped at MAX_MATCHES_PER_PATTERN), or None if timed out.
    """
    compiled = re.compile(pattern, re.DOTALL)

    # For short content, just run directly (no timeout overhead)
    if len(content) < 5000:
        try:
            matches = []
            for i, match in enumerate(compiled.finditer(content)):
                if i >= MAX_MATCHES_PER_PATTERN:
                    break
                matches.append(match)
            return matches
        except (re.error, RuntimeError):
            return None

    # For longer content, use threading-based timeout
    try:
        import threading

        result = [None]  # Use list to share between threads
        error = [None]

        def _run():
            try:
                matches = []
                for i, match in enumerate(compiled.finditer(content)):
                    if i >= MAX_MATCHES_PER_PATTERN:
                        break
                    matches.append(match)
                result[0] = matches
            except (re.error, RuntimeError) as e:
                error[0] = e

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=timeout)

        if worker.is_alive():
            # Thread is still running — it will be cleaned up at exit
            # because it's daemon. Log and skip this pattern.
            logger.debug(f"Regex timed out after {timeout}s for pattern: {pattern[:80]}...")
            return None

        if error[0]:
            return None

        return result[0]

    except Exception:
        # Fallback: just try running directly with a result limit
        try:
            matches = []
            for i, match in enumerate(compiled.finditer(content)):
                if i >= MAX_MATCHES_PER_PATTERN:
                    break
                matches.append(match)
            return matches
        except (re.error, RuntimeError):
            return None

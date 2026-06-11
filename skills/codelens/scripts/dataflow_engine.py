"""
Dataflow Engine for CodeLens — v3
Tracks data flow from source to sink for security analysis.
Answers: "Does user input ever reach a DB query without sanitization?"
Answers: "Does env var data ever reach an HTTP response without validation?"

This is the most powerful tool for AI bug-finding: it traces WHERE data goes,
not just WHO calls what. Call chains ≠ data chains.

Architecture:
- Sources: Where data enters the system (user input, env vars, API responses, files)
- Sinks: Where data could be dangerous (DB queries, HTML output, HTTP responses, file writes, eval/exec)
- Sanitizers: Functions that make data safe (escape, validate, sanitize, encode)
- Propagators: Functions that pass data through (identity, transform, assign)

Data flows through: source → propagator* → (sanitizer | sink)
If data reaches a sink without a sanitizer, it's a taint violation.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict, deque
from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Source Patterns (where data enters) ───────────────────────

SOURCE_PATTERNS = {
    # JS/TS user input
    "js_user_input": {
        "patterns": [
            r"req\.(?:body|params|query|headers|cookies)",
            r"request\.(?:body|params|query)",
            r"event\.(?:body|queryStringParameters|pathParameters)",
            r"ctx\.(?:request|req)\.(?:body|params|query)",
            r"this\.(?:body|params|query)",
            r"req\.get\s*\(",
            r"request\.get\s*\(",
        ],
        "label": "user_input",
        "severity": "high",
        "languages": {".js", ".ts", ".tsx", ".jsx", ".mjs"}
    },
    # DOM input
    "js_dom_input": {
        "patterns": [
            r"document\.getElementById\s*\([^)]+\)\.value",
            r"document\.querySelector\s*\([^)]+\)\.value",
            r"event\.target\.value",
            r"e\.target\.value",
            r"this\.value",
            r"input\.value",
            r"select\.value",
            r"textarea\.value",
            r"form\.\w+\.value",
            r"target\.value",
            r"prompt\s*\(",
            r"window\.location\.(?:href|search|hash)",
        ],
        "label": "dom_input",
        "severity": "medium",
        "languages": {".js", ".ts", ".tsx", ".jsx", ".mjs"}
    },
    # Environment variables
    "env_vars": {
        "patterns": [
            r"process\.env\.",
            r"os\.environ(?:\[|\.get)",
            r"std::env::var",
            r"dotenv::var",
            r"env!\(",
        ],
        "label": "env_var",
        "severity": "low",
        "languages": {".js", ".ts", ".tsx", ".jsx", ".mjs", ".py", ".rs"}
    },
    # File system reads
    "file_reads": {
        "patterns": [
            r"fs\.read(?:File|FileSync|Dir|DirSync)",
            r"readFile\s*\(",
            r"open\s*\([^)]*['\"]r",
            r"File::open",
            r"std::fs::read",
            r"with\s+open\s*\(",
        ],
        "label": "file_input",
        "severity": "medium",
        "languages": {".js", ".ts", ".tsx", ".jsx", ".mjs", ".py", ".rs"}
    },
    # API/network responses
    "api_responses": {
        "patterns": [
            r"(?:fetch|axios|http\.get|https\.get|request)\s*\(",
            # axios method calls: axios.get(), axios.post(), etc.
            r"axios\.(?:get|post|put|delete|patch|head|options|request)\s*\(",
            # XMLHttpRequest
            r"XMLHttpRequest",
            r"xhr\.(?:open|send)\s*\(",
            r"\.open\s*\(\s*['\"](?:GET|POST|PUT|DELETE|PATCH)",
            # jQuery AJAX
            r"\$\.(?:ajax|get|post|getJSON)\s*\(",
            r"\.json\s*\(\s*\)",
            r"response\.data",
            r"resp\.body",
            r"HttpResponse",
            r"reqwest::get",
        ],
        "label": "api_response",
        "severity": "medium",
        "languages": {".js", ".ts", ".tsx", ".jsx", ".mjs", ".py", ".rs"}
    },
}

# ─── Sink Patterns (where data could be dangerous) ────────────

SINK_PATTERNS = {
    # Database queries
    "db_query": {
        "patterns": [
            r"(?:query|execute|raw|run)\s*\(\s*(?:`|\"|\')",
            r"\.query\s*\(",
            r"sql\s*`",
            r"cursor\.execute\s*\(",
            r"db\.(?:run|exec|query)",
            r"knex\.raw\s*\(",
            r"sequelize\.query\s*\(",
            r"Model\.(?:raw|query)",
        ],
        "label": "database_query",
        "severity": "critical",
        "description": "Data reaches SQL query — SQL injection risk"
    },
    # HTML output
    "html_output": {
        "patterns": [
            r"innerHTML\s*=",
            r"outerHTML\s*=",
            r"document\.write\s*\(",
            r"dangerouslySetInnerHTML",
            r"v-html\s*=",
            r"\{\!\s*\w+\s*!\}",  # Unescaped template
            r"res\.(?:send|write|end)\s*\(",
            r"response\.(?:write|send)\s*\(",
        ],
        "label": "html_output",
        "severity": "critical",
        "description": "Data rendered as HTML — XSS risk"
    },
    # Command execution
    "command_exec": {
        "patterns": [
            r"eval\s*\(",
            r"Function\s*\(",
            r"setTimeout\s*\(\s*[\"']",
            r"setInterval\s*\(\s*[\"']",
            r"exec(?:Sync)?\s*\(",
            r"spawn(?:Sync)?\s*\(",
            r"child_process\.",
            r"os\.system\s*\(",
            r"subprocess\.(?:call|run|Popen)",
            r"Command::new",
            r"std::process::Command",
        ],
        "label": "command_execution",
        "severity": "critical",
        "description": "Data reaches command execution — code injection risk"
    },
    # File writes
    "file_write": {
        "patterns": [
            r"fs\.write(?:File|FileSync|)",
            r"writeFile\s*\(",
            r"\.pipe\s*\(",
            r"open\s*\([^)]*['\"]w",
            r"std::fs::write",
            r"File::create",
        ],
        "label": "file_write",
        "severity": "high",
        "description": "Data written to file — path traversal / data integrity risk"
    },
    # HTTP response headers
    "http_headers": {
        "patterns": [
            r"res\.(?:setHeader|set|header)\s*\(",
            r"response\.setHeader\s*\(",
            r"\.redirect\s*\(",
        ],
        "label": "http_header",
        "severity": "high",
        "description": "Data in HTTP header — header injection risk"
    },
}

# ─── Sanitizer Patterns (functions that make data safe) ───────

SANITIZER_PATTERNS = {
    "html_escape": {
        "patterns": [
            r"escape(?:Html|HTML)?\s*\(",
            r"sanitize(?:Html|HTML)?\s*\(",
            r"encodeURI(?:Component)?\s*\(",
            r"DOMPurify\.(?:sanitize|clean)\s*\(",
            r"he\.(?:encode|escape)\s*\(",
            r"htmlspecialchars\s*\(",
            r"html_escape\s*\(",
            r"bleach\.clean\s*\(",
        ],
        "sanitizes_for": {"html_output"},
        "label": "html_sanitizer"
    },
    "sql_escape": {
        "patterns": [
            r"escape(?:Sql|SQL)?\s*\(",
            r"sanitize(?:Sql|SQL)?\s*\(",
            r"parameterize\s*\(",
            r"\.escape\s*\(",
            r"mysql\.escape\s*\(",
            r"pg\.escape\s*\(",
            r"\$\{?\d+\}?",  # Parameterized query placeholder
            r"\?\s*[,\)]",   # Parameterized query placeholder (?)
        ],
        "sanitizes_for": {"db_query"},
        "label": "sql_sanitizer"
    },
    "input_validation": {
        "patterns": [
            r"validat(?:e|ion|or)\s*\(",
            r"joi\.validate\s*\(",
            r"z\.object\s*\(",
            r"yup\.\w+\s*\(",
            r"ajv\.validate\s*\(",
            r"isValid(?:ation)?\s*\(",
            r"check\s*\(",
            r"assert\s*\(",
            r"typeof\s+\w+\s*===",
            r"instanceof\s+\w+",
        ],
        "sanitizes_for": {"db_query", "html_output", "command_exec", "http_header"},
        "label": "input_validator"
    },
    "path_sanitizer": {
        "patterns": [
            r"path\.(?:normalize|resolve|basename|dirname)\s*\(",
            r"path\.join\s*\(",
            r"sanitize\s*\(\s*(?:filename|path)",
            r"realpath\s*\(",
        ],
        "sanitizes_for": {"file_write"},
        "label": "path_sanitizer"
    },
}

# ─── Propagator Patterns (functions that pass data through) ───

PROPAGATOR_PATTERNS = [
    # Variable assignment / return
    r"(?:const|let|var)\s+\w+\s*=\s*\w+",
    r"return\s+\w+",
    r"\w+\s*=\s*\w+",
    # String concatenation / template
    r"[`\"'].*\$\{",
    r"\w+\s*\+\s*\w+",
    # Spread / Object.assign
    r"\.\.\.\w+",
    r"Object\.assign\s*\(",
    # JSON methods
    r"JSON\.(?:parse|stringify)\s*\(",
    # Map/filter/transform
    r"\.map\s*\(",
    r"\.filter\s*\(",
    r"\.reduce\s*\(",
    r"\.forEach\s*\(",
    r"\.transform\s*\(",
]

# ─── Ignore dirs ──────────────────────────────────────────────

SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}


def trace_dataflow(
    workspace: str,
    source: Optional[str] = None,
    sink: Optional[str] = None,
    max_depth: int = 15,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Trace data flow from sources to sinks across the workspace.

    If source is specified, trace where that source data flows.
    If sink is specified, trace what data reaches that sink.
    If neither specified, find ALL source→sink paths.

    Args:
        workspace: Absolute path to workspace
        source: Optional source filter (e.g., "user_input", "env_var", or a variable name)
        sink: Optional sink filter (e.g., "db_query", "html_output")
        max_depth: Maximum data flow chain depth
        config: CodeLens config

    Returns:
        Dict with taint flows, violations, and safe paths
    """
    workspace = os.path.abspath(workspace)

    # Scan all source files for sources, sinks, and sanitizers
    source_hits = []  # Where data enters
    sink_hits = []    # Where data could be dangerous
    sanitizer_hits = []  # Where data gets cleaned
    propagator_hits = []  # Where data flows through

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

            lines = content.split('\n')

            # Detect sources
            for src_key, src_def in SOURCE_PATTERNS.items():
                if ext not in src_def.get("languages", SOURCE_EXTENSIONS):
                    continue
                if source and source != src_key and source != src_def["label"] and source not in src_key:
                    continue

                for pattern in src_def["patterns"]:
                    for match in re.finditer(pattern, content):
                        line_num = content[:match.start()].count('\n') + 1
                        source_hits.append({
                            "source_type": src_key,
                            "label": src_def["label"],
                            "file": rel_path,
                            "line": line_num,
                            "match": lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            "severity": src_def["severity"],
                            "col": match.start() - content[:match.start()].rfind('\n') - 1
                        })

            # Detect sinks
            for sink_key, sink_def in SINK_PATTERNS.items():
                if sink and sink != sink_key and sink != sink_def["label"] and sink not in sink_key:
                    continue

                for pattern in sink_def["patterns"]:
                    for match in re.finditer(pattern, content):
                        line_num = content[:match.start()].count('\n') + 1
                        sink_hits.append({
                            "sink_type": sink_key,
                            "label": sink_def["label"],
                            "file": rel_path,
                            "line": line_num,
                            "match": lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            "severity": sink_def["severity"],
                            "description": sink_def["description"],
                            "col": match.start() - content[:match.start()].rfind('\n') - 1
                        })

            # Detect sanitizers
            for san_key, san_def in SANITIZER_PATTERNS.items():
                for pattern in san_def["patterns"]:
                    for match in re.finditer(pattern, content):
                        line_num = content[:match.start()].count('\n') + 1
                        sanitizer_hits.append({
                            "sanitizer_type": san_key,
                            "label": san_def["label"],
                            "file": rel_path,
                            "line": line_num,
                            "match": lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            "sanitizes_for": san_def["sanitizes_for"]
                        })

    # ─── Build data flow graph ──────────────────────────
    # Group sources and sinks by file, then trace within and across files
    flows = _build_flows(source_hits, sink_hits, sanitizer_hits, workspace, max_depth)

    # ─── Classify flows ─────────────────────────────────
    violations = []  # Source → Sink WITHOUT sanitizer
    safe_paths = []  # Source → Sink WITH sanitizer
    untraced_sources = []  # Sources that don't reach any sink

    sinks_by_file = defaultdict(list)
    for s in sink_hits:
        sinks_by_file[s["file"]].append(s)

    sanitizers_by_file = defaultdict(list)
    for s in sanitizer_hits:
        sanitizers_by_file[s["file"]].append(s)

    for flow in flows:
        if flow.get("reaches_sink"):
            # Check if a sanitizer exists between source and sink
            has_sanitizer = _check_sanitizer(
                flow["source"], flow["sink"],
                sanitizer_hits, sanitizers_by_file
            )

            flow["sanitized"] = has_sanitizer

            if has_sanitizer:
                safe_paths.append(flow)
            else:
                violations.append(flow)
        else:
            untraced_sources.append(flow["source"])

    # ─── Compute risk ──────────────────────────────────
    risk = _compute_dataflow_risk(violations)

    # ─── Generate recommendations ──────────────────────
    recommendations = _generate_dataflow_recommendations(violations, safe_paths)

    return {
        "status": "ok",
        "workspace": workspace,
        "source_filter": source,
        "sink_filter": sink,
        "stats": {
            "sources_found": len(source_hits),
            "sinks_found": len(sink_hits),
            "sanitizers_found": len(sanitizer_hits),
            "violations": len(violations),
            "safe_paths": len(safe_paths),
            "untraced_sources": len(untraced_sources)
        },
        "risk": risk,
        "violations": violations,
        "safe_paths": safe_paths,
        "untraced_sources": untraced_sources[:50],  # Cap to avoid explosion
        "recommendations": recommendations
    }


def _build_flows(
    sources: List[Dict],
    sinks: List[Dict],
    sanitizers: List[Dict],
    workspace: str,
    max_depth: int
) -> List[Dict]:
    """Build potential data flows from sources to sinks.

    Strategy:
    1. Same-file flows: Source and sink in same file, source line < sink line
    2. Cross-file flows: Source in file A, sink in file B that imports from A
    """
    flows = []
    sources_by_file = defaultdict(list)
    for s in sources:
        sources_by_file[s["file"]].append(s)

    sinks_by_file = defaultdict(list)
    for s in sinks:
        sinks_by_file[s["file"]].append(s)

    # Build import map for cross-file analysis
    import_map = _build_import_map(workspace)

    # Same-file flows
    for file_path, file_sources in sources_by_file.items():
        file_sinks = sinks_by_file.get(file_path, [])

        for src in file_sources:
            reached_sink = None

            # Find the nearest sink after this source in the same file
            for snk in file_sinks:
                if snk["line"] > src["line"]:
                    # Check if there's a data flow path
                    # Heuristic: same variable or function chain
                    flow_chain = _trace_intra_file_flow(
                        workspace, file_path, src, snk, max_depth
                    )
                    if flow_chain:
                        reached_sink = snk
                        flows.append({
                            "source": src,
                            "sink": snk,
                            "flow_chain": flow_chain,
                            "reaches_sink": True,
                            "flow_type": "intra_file"
                        })
                        break

            if not reached_sink:
                # Check cross-file flows
                # Find files that import this file
                importers = import_map.get(file_path, [])
                for importer in importers:
                    importer_sinks = sinks_by_file.get(importer, [])
                    for snk in importer_sinks:
                        flows.append({
                            "source": src,
                            "sink": snk,
                            "flow_chain": [
                                {"file": src["file"], "line": src["line"], "type": "source"},
                                {"file": importer, "type": "cross_file_import"},
                                {"file": snk["file"], "line": snk["line"], "type": "sink"}
                            ],
                            "reaches_sink": True,
                            "flow_type": "cross_file"
                        })

                if not importers:
                    flows.append({
                        "source": src,
                        "sink": None,
                        "flow_chain": [],
                        "reaches_sink": False,
                        "flow_type": "untraced"
                    })

    return flows


def _trace_intra_file_flow(
    workspace: str, file_path: str,
    source: Dict, sink: Dict,
    max_depth: int
) -> List[Dict]:
    """Trace data flow within a single file from source line to sink line.

    Uses heuristic: look for variable assignments, function calls, and
    string concatenations between source and sink lines.
    """
    full_path = os.path.join(workspace, file_path)
    if not os.path.exists(full_path):
        return []

    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except IOError:
        return []

    chain = [{
        "file": file_path,
        "line": source["line"],
        "type": "source",
        "snippet": lines[source["line"] - 1].strip() if source["line"] <= len(lines) else ""
    }]

    # Extract variable name from source match
    src_line = lines[source["line"] - 1].strip() if source["line"] <= len(lines) else ""
    var_name = _extract_variable_name(src_line)

    # Scan lines between source and sink for data propagation
    start_line = source["line"]
    end_line = min(sink["line"], start_line + max_depth)

    current_var = var_name
    for line_num in range(start_line, end_line):
        if line_num >= len(lines):
            break

        line = lines[line_num].strip()

        # Skip empty lines and comments
        if not line or line.startswith('//') or line.startswith('#') or line.startswith('/*'):
            continue

        # Check if current variable appears in this line
        if current_var and current_var in line:
            # Check if it's an assignment to a new variable
            new_var = _extract_assignment_target(line, current_var)
            if new_var and new_var != current_var:
                chain.append({
                    "file": file_path,
                    "line": line_num + 1,
                    "type": "propagation",
                    "via": "assignment",
                    "from_var": current_var,
                    "to_var": new_var,
                    "snippet": line
                })
                current_var = new_var
            elif "return" in line:
                chain.append({
                    "file": file_path,
                    "line": line_num + 1,
                    "type": "propagation",
                    "via": "return",
                    "var": current_var,
                    "snippet": line
                })

    # Add sink
    chain.append({
        "file": file_path,
        "line": sink["line"],
        "type": "sink",
        "sink_label": sink["label"],
        "snippet": lines[sink["line"] - 1].strip() if sink["line"] <= len(lines) else ""
    })

    return chain


def _extract_variable_name(line: str) -> Optional[str]:
    """Extract the variable name from a source line."""
    # const/let/var x = ...
    m = re.match(r'(?:const|let|var)\s+(\w+)\s*=', line)
    if m:
        return m.group(1)
    # x = ...
    m = re.match(r'(\w+)\s*=\s*', line)
    if m:
        return m.group(1)
    # function param: (req, res) => or function(req, res)
    m = re.match(r'(?:function\s*\(|\()(?:\s*(\w+)\s*,)', line)
    if m:
        return m.group(1)
    return None


def _extract_assignment_target(line: str, source_var: str) -> Optional[str]:
    """Check if line assigns source_var to a new variable."""
    # const/let/var newVar = ...sourceVar...
    m = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*.*' + re.escape(source_var), line)
    if m:
        return m.group(1)
    # newVar = ...sourceVar...
    m = re.match(r'(\w+)\s*=\s*.*' + re.escape(source_var), line)
    if m:
        return m.group(1)
    return None


def _build_import_map(workspace: str) -> Dict[str, List[str]]:
    """Build a map of file → files that import it."""
    import_map: Dict[str, List[str]] = defaultdict(list)
    reverse_map: Dict[str, List[str]] = defaultdict(list)

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

            # Parse imports
            for m in re.finditer(r'(?:import|require)\s*.*?from\s*["\'](\.[^"\']+)["\']', content):
                import_path = m.group(1)
                # Resolve relative import
                from_dir = os.path.dirname(rel_path)
                resolved = os.path.normpath(os.path.join(from_dir, import_path))
                for ext_try in ['', '.js', '.ts', '.tsx', '/index.js', '/index.ts']:
                    if os.path.exists(os.path.join(workspace, resolved + ext_try)):
                        resolved = resolved + ext_try
                        break
                reverse_map[resolved].append(rel_path)

    return reverse_map


def _check_sanitizer(
    source: Dict, sink: Dict,
    all_sanitizers: List[Dict],
    sanitizers_by_file: Dict[str, List[Dict]]
) -> bool:
    """Check if a sanitizer exists between source and sink."""
    sink_label = sink.get("label", "")

    # Check same-file sanitizers
    for san in sanitizers_by_file.get(source["file"], []):
        # Sanitizer must be between source and sink
        if san["line"] > source["line"] and san["line"] < sink["line"]:
            if sink_label in san.get("sanitizes_for", set()):
                return True

    # Check cross-file: any file in the import chain has relevant sanitizer
    for san in all_sanitizers:
        if sink_label in san.get("sanitizes_for", set()):
            # Heuristic: if sanitizer is in source file or sink file, it's in the chain
            if san["file"] == source["file"] or san["file"] == sink["file"]:
                return True

    return False


def _compute_dataflow_risk(violations: List[Dict]) -> str:
    """Compute overall risk based on violations found."""
    if not violations:
        return "none"

    max_severity = "low"
    for v in violations:
        sink_sev = v.get("sink", {}).get("severity", "low")
        source_sev = v.get("source", {}).get("severity", "low")

        if sink_sev == "critical" or source_sev == "high":
            return "critical"
        elif sink_sev == "high" or source_sev == "medium":
            max_severity = "high"
        elif max_severity == "low":
            max_severity = "medium"

    return max_severity


def _generate_dataflow_recommendations(
    violations: List[Dict],
    safe_paths: List[Dict]
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    if not violations:
        recs.append("No taint violations found. Data flow appears safe.")
        if safe_paths:
            recs.append(f"Found {len(safe_paths)} sanitized data flow(s) — good practice.")
        return recs

    # Group violations by sink type
    by_sink = defaultdict(list)
    for v in violations:
        sink_label = v.get("sink", {}).get("label", "unknown")
        by_sink[sink_label].append(v)

    for sink_type, viols in by_sink.items():
        if sink_type == "database_query":
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching SQL queries. "
                f"Use parameterized queries or escape inputs. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )
        elif sink_type == "html_output":
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching HTML output. "
                f"Escape HTML entities before rendering. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )
        elif sink_type == "command_execution":
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching command execution. "
                f"CRITICAL: Use allowlists and avoid eval/exec. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )
        elif sink_type == "file_write":
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching file writes. "
                f"Validate and normalize paths before writing. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )
        elif sink_type == "http_header":
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching HTTP headers. "
                f"Validate header values and strip newlines. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )
        else:
            recs.append(
                f"FOUND {len(viols)} unsanitized data flow(s) reaching {sink_type}. "
                f"Add validation/sanitization. "
                f"Files: {', '.join(set(v['source']['file'] for v in viols))}"
            )

    return recs

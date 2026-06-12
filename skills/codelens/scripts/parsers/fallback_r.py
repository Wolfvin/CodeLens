"""
Fallback R Parser for CodeLens — regex-based extraction.
Extracts functions, S3/S4/R6 classes, variables, library calls,
source directives, pipe operators, Shiny patterns, and call edges.
"""

import re
from typing import Dict, List, Any, Optional


# R keywords and builtins to skip when detecting calls
_R_KEYWORDS = frozenset({
    'if', 'else', 'for', 'while', 'repeat', 'function', 'in', 'next',
    'break', 'return', 'switch', 'NULL', 'NA', 'NA_real_', 'NA_integer_',
    'NA_complex_', 'NA_character_', 'TRUE', 'FALSE', 'Inf', 'NaN',
    'library', 'require', 'source', 'local', 'invisible', 'on.exit',
    # Common builtins that aren't interesting as call targets
    'print', 'cat', 'message', 'warning', 'stop', 'tryCatch', 'withCallingHandlers',
    'c', 'list', 'data.frame', 'matrix', 'array', 'vector', 'integer',
    'numeric', 'character', 'logical', 'double', 'complex', 'raw',
    'length', 'nrow', 'ncol', 'dim', 'names', 'rownames', 'colnames',
    'sum', 'mean', 'min', 'max', 'range', 'which', 'any', 'all',
    'is.null', 'is.na', 'is.character', 'is.numeric', 'is.integer',
    'is.logical', 'is.data.frame', 'is.list', 'is.vector',
    'as.character', 'as.numeric', 'as.integer', 'as.logical',
    'as.data.frame', 'as.list', 'as.vector', 'as.matrix',
    'paste', 'paste0', 'sprintf', 'substr', 'substring', 'nchar', 'grep',
    'grepl', 'sub', 'gsub', 'regexpr', 'gregexpr',
    'strsplit', 'toupper', 'tolower', 'trimws',
    'readline', 'readLines', 'writeLines', 'file', 'dir', 'list.files',
    'exists', 'get', 'assign', 'rm', 'ls', 'gc', 'sys.time',
    'lapply', 'sapply', 'vapply', 'apply', 'tapply', 'mapply', 'rapply',
    'Map', 'Reduce', 'Filter', 'Find', 'Position',
    'do.call', 'call', 'match.call', 'match.arg', 'formals', 'body', 'args',
    'eval', 'evalq', 'eval.parent', 'quote', 'substitute', 'expression',
    'parse', 'deparse', 'bquote', 'sys.call', 'sys.frame',
    'system', 'system2', 'shell', 'proc.time', 'Sys.time', 'Sys.sleep',
    'T', 'F', 'pi', 'letters', 'LETTERS', 'month.name', 'month.abb',
})


def parse_r_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse R source using regex — extracts functions, classes, imports, and call edges.

    Returns dict with 'nodes' and 'edges' in the format expected by
    the backend registry and edge_resolver:
    - nodes: [{id, name, fn, type, file, line, ...}]
    - edges: [{from, to, file, line, type}, ...]
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Track defined function names → node_id for this file
    defined_fns: Dict[str, str] = {}

    # ─── Pass 1: Extract declarations ──────────────────────────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # --- S4 Classes: setClass("ClassName", ...) ---
        m = re.match(r'\s*setClass\s*\(\s*["\'](\w+)["\']', line)
        if m:
            cls_name = m.group(1)
            node_id = f"{rel_path}:{i}:s4:{cls_name}"
            nodes.append({
                "id": node_id,
                "type": "s4_class",
                "name": cls_name,
                "fn": cls_name,
                "file": rel_path,
                "line": i,
            })
            defined_fns[cls_name] = node_id
            # Detect contains= (inheritance)
            inh = re.search(r'contains\s*=\s*["\'](\w+)["\']', line)
            if inh:
                edges.append({
                    "from": node_id,
                    "to": inh.group(1),
                    "file": rel_path,
                    "line": i,
                    "type": "extends",
                })
            continue

        # --- S4 Generics: setGeneric("name", ...) ---
        m = re.match(r'\s*setGeneric\s*\(\s*["\'](\w+)["\']', line)
        if m:
            gen_name = m.group(1)
            node_id = f"{rel_path}:{i}:s4generic:{gen_name}"
            nodes.append({
                "id": node_id,
                "type": "s4_class",
                "name": gen_name,
                "fn": gen_name,
                "file": rel_path,
                "line": i,
            })
            defined_fns[gen_name] = node_id
            continue

        # --- S4 Methods: setMethod("name", ...) ---
        m = re.match(r'\s*setMethod\s*\(\s*["\'](\w+)["\']', line)
        if m:
            meth_name = m.group(1)
            # Try to detect the signature class
            sig = re.search(r'signature\s*=\s*["\'](\w+)["\']', line)
            sig_cls = sig.group(1) if sig else ""
            display_name = f"{meth_name}.{sig_cls}" if sig_cls else meth_name
            node_id = f"{rel_path}:{i}:s4method:{display_name}"
            nodes.append({
                "id": node_id,
                "type": "s4_class",
                "name": display_name,
                "fn": meth_name,
                "file": rel_path,
                "line": i,
            })
            defined_fns[meth_name] = node_id
            if sig_cls:
                edges.append({
                    "from": node_id,
                    "to": sig_cls,
                    "file": rel_path,
                    "line": i,
                    "type": "extends",
                })
            continue

        # --- S4 Reference Classes: setRefClass("name", ...) ---
        m = re.match(r'\s*setRefClass\s*\(\s*["\'](\w+)["\']', line)
        if m:
            ref_name = m.group(1)
            node_id = f"{rel_path}:{i}:s4ref:{ref_name}"
            nodes.append({
                "id": node_id,
                "type": "s4_class",
                "name": ref_name,
                "fn": ref_name,
                "file": rel_path,
                "line": i,
            })
            defined_fns[ref_name] = node_id
            continue

        # --- R6 Classes: R6Class("ClassName", ...) ---
        m = re.match(r'\s*(\w+)\s*(?:<-|<<-|=)\s*R6Class\s*\(\s*["\'](\w+)["\']', line)
        if m:
            var_name = m.group(1)
            cls_name = m.group(2)
            display_name = cls_name if cls_name else var_name
            node_id = f"{rel_path}:{i}:r6:{display_name}"
            nodes.append({
                "id": node_id,
                "type": "r6_class",
                "name": display_name,
                "fn": display_name,
                "file": rel_path,
                "line": i,
            })
            defined_fns[display_name] = node_id
            defined_fns[var_name] = node_id
            # Detect inherit= (R6 inheritance)
            inh = re.search(r'inherit\s*=\s*(\w+)', line)
            if inh:
                edges.append({
                    "from": node_id,
                    "to": inh.group(1),
                    "file": rel_path,
                    "line": i,
                    "type": "extends",
                })
            continue

        # --- Functions: name <- function(...) or name = function(...) ---
        m = re.match(r'\s*([a-zA-Z_.][a-zA-Z0-9_.]*)\s*(<-|<<-|=)\s*function\s*\(', line)
        if m:
            fn_name = m.group(1)
            assign_op = m.group(2)
            # Check if this is an S3 method: method.class <- function(...)
            s3_match = re.match(r'^([a-zA-Z_.][a-zA-Z0-9_.]*)\.([a-zA-Z_.][a-zA-Z0-9_.]*)$', fn_name)
            if s3_match:
                method_name = s3_match.group(1)
                class_name = s3_match.group(2)
                node_id = f"{rel_path}:{i}:s3:{fn_name}"
                nodes.append({
                    "id": node_id,
                    "type": "s3_method",
                    "name": fn_name,
                    "fn": fn_name,
                    "file": rel_path,
                    "line": i,
                    "s3_method": method_name,
                    "s3_class": class_name,
                })
                defined_fns[fn_name] = node_id
                edges.append({
                    "from": node_id,
                    "to": class_name,
                    "file": rel_path,
                    "line": i,
                    "type": "extends",
                })
            else:
                # Regular function
                node_id = f"{rel_path}:{i}:fn:{fn_name}"
                node_type = "function"
                nodes.append({
                    "id": node_id,
                    "type": node_type,
                    "name": fn_name,
                    "fn": fn_name,
                    "file": rel_path,
                    "line": i,
                })
                defined_fns[fn_name] = node_id

                # Detect Shiny server pattern: server <- function(input, output, session)
                if fn_name == "server":
                    if re.search(r'function\s*\(\s*input\s*,\s*output', line):
                        nodes[-1]["shiny"] = "server"

                # Detect Shiny ui pattern: ui <- fluidPage(...)
                if fn_name == "ui":
                    if re.search(r'fluidPage|navbarPage|bootstrapPage|fixedPage|fillPage|flowLayout|sidebarLayout', line):
                        nodes[-1]["shiny"] = "ui"
            continue

        # --- Shiny: shinyServer(function(...) ---
        m = re.match(r'\s*shinyServer\s*\(\s*function\s*\(', line)
        if m:
            node_id = f"{rel_path}:{i}:shiny:server"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": "shinyServer",
                "fn": "shinyServer",
                "file": rel_path,
                "line": i,
                "shiny": "server",
            })
            defined_fns["shinyServer"] = node_id
            continue

        # --- Shiny: shinyUI(fluidPage(...) ---
        m = re.match(r'\s*shinyUI\s*\(\s*(\w+)', line)
        if m:
            node_id = f"{rel_path}:{i}:shiny:ui"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": "shinyUI",
                "fn": "shinyUI",
                "file": rel_path,
                "line": i,
                "shiny": "ui",
            })
            defined_fns["shinyUI"] = node_id
            continue

        # --- Shiny UI variable: name <- fluidPage(...), server <- function(input, output) ---
        m = re.match(
            r'\s*([a-zA-Z_.][a-zA-Z0-9_.]*)\s*(<-|<<-|=)\s*(fluidPage|navbarPage|bootstrapPage|fixedPage|fillPage|flowLayout|sidebarLayout|pageWithSidebar|basicPage)\s*\(',
            line,
        )
        if m:
            var_name = m.group(1)
            ui_fn = m.group(3)
            node_id = f"{rel_path}:{i}:shiny:ui:{var_name}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": var_name,
                "fn": var_name,
                "file": rel_path,
                "line": i,
                "shiny": "ui",
                "ui_fn": ui_fn,
            })
            defined_fns[var_name] = node_id
            edges.append({
                "from": node_id,
                "to": ui_fn,
                "file": rel_path,
                "line": i,
                "type": "calls",
            })
            continue

        # --- Shiny: output$plot <- renderPlot({... ---
        m = re.match(r'\s*output\$(\w+)\s*(<-|<<-)\s*(\w+)\s*\(', line)
        if m:
            output_name = m.group(1)
            render_fn = m.group(3)
            node_id = f"{rel_path}:{i}:shiny:output:{output_name}"
            nodes.append({
                "id": node_id,
                "type": "function",
                "name": f"output${output_name}",
                "fn": output_name,
                "file": rel_path,
                "line": i,
                "shiny": "output",
                "render_fn": render_fn,
            })
            defined_fns[output_name] = node_id
            edges.append({
                "from": node_id,
                "to": render_fn,
                "file": rel_path,
                "line": i,
                "type": "calls",
            })
            continue

        # --- Variables: name <- value, name <<- value (skip function defs already handled) ---
        m = re.match(r'\s*([a-zA-Z_.][a-zA-Z0-9_.]*)\s*(<-|<<-)\s*(?!function\b)(.+)', line)
        if m:
            var_name = m.group(1)
            assign_op = m.group(2)
            # Skip if it's already been captured as a function, R6 class, etc.
            if var_name not in defined_fns and var_name not in _R_KEYWORDS:
                # Skip common R patterns that aren't meaningful variables
                if var_name not in ('.', '..', '...'):
                    node_id = f"{rel_path}:{i}:var:{var_name}"
                    nodes.append({
                        "id": node_id,
                        "type": "variable",
                        "name": var_name,
                        "fn": var_name,
                        "file": rel_path,
                        "line": i,
                        "super_assign": assign_op == "<<-",
                    })
                    defined_fns[var_name] = node_id
            continue

    # ─── Pass 1b: Multi-line inheritance detection for S4/R6 classes ───
    # setClass / R6Class definitions often span multiple lines;
    # scan ahead from each S4/R6 node for contains= / inherit=.
    # Build a set of lines where other top-level nodes start to use as stop boundaries.
    _node_lines = {n.get("line", 0) for n in nodes if n.get("line", 0) > 0}
    for node in nodes:
        if node.get("type") not in ("s4_class", "r6_class"):
            continue
        n_line = node.get("line", 0)
        # Scan up to 10 lines after the definition for inheritance,
        # but stop if we encounter another top-level definition or a closing paren at depth 0
        depth = 0
        for offset in range(0, 10):
            check = n_line - 1 + offset
            if check >= len(lines):
                break
            scan_line = lines[check]
            # Track parenthesis depth to stop at end of setClass/R6Class call
            depth += scan_line.count('(') - scan_line.count(')')
            if depth <= 0 and offset > 0:
                break
            # Stop if we hit another top-level definition (other than this node's line)
            # Only check when outside the current call's parentheses
            if offset > 0 and (check + 1) in _node_lines and depth <= 1:
                break
            # S4: contains = "ParentClass"
            inh = re.search(r'contains\s*=\s*["\'](\w+)["\']', scan_line)
            if inh:
                parent = inh.group(1)
                # Avoid duplicate edges
                already = any(
                    e.get("from") == node["id"] and e.get("to") == parent and e.get("type") == "extends"
                    for e in edges
                )
                if not already:
                    edges.append({
                        "from": node["id"],
                        "to": parent,
                        "file": rel_path,
                        "line": check + 1,
                        "type": "extends",
                    })
            # R6: inherit = ParentClass
            inh = re.search(r'inherit\s*=\s*(\w+)', scan_line)
            if inh:
                parent = inh.group(1)
                already = any(
                    e.get("from") == node["id"] and e.get("to") == parent and e.get("type") == "extends"
                    for e in edges
                )
                if not already:
                    edges.append({
                        "from": node["id"],
                        "to": parent,
                        "file": rel_path,
                        "line": check + 1,
                        "type": "extends",
                    })

    # ─── Pass 2: Extract imports and sources ───────────────────────

    # Build function body ranges early (used for owner resolution in passes 2-5)
    fn_ranges = _build_fn_ranges(lines, nodes)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        owner_node = _find_owner_node(nodes, i, fn_ranges)

        # --- library(pkg) and require(pkg) ---
        for m in re.finditer(r'\b(?:library|require)\s*\(\s*([a-zA-Z][a-zA-Z0-9._]*)\s*\)', stripped):
            pkg_name = m.group(1)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to": pkg_name,
                    "file": rel_path,
                    "line": i,
                    "type": "imports",
                })
            else:
                edges.append({
                    "from": rel_path,
                    "to": pkg_name,
                    "file": rel_path,
                    "line": i,
                    "type": "imports",
                })

        # --- Namespace access: pkg::fun or pkg:::fun ---
        for m in re.finditer(r'\b([a-zA-Z][a-zA-Z0-9._]*)\s*:::?([a-zA-Z_.][a-zA-Z0-9_.]*)', stripped):
            pkg_name = m.group(1)
            fn_name = m.group(2)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to": f"{pkg_name}::{fn_name}",
                    "file": rel_path,
                    "line": i,
                    "type": "imports",
                })
            else:
                edges.append({
                    "from": rel_path,
                    "to": f"{pkg_name}::{fn_name}",
                    "file": rel_path,
                    "line": i,
                    "type": "imports",
                })

        # --- source("file.R") ---
        for m in re.finditer(r'\bsource\s*\(\s*["\']([^"\']+)["\']\s*\)', stripped):
            src_file = m.group(1)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to": src_file,
                    "file": rel_path,
                    "line": i,
                    "type": "sources",
                })
            else:
                edges.append({
                    "from": rel_path,
                    "to": src_file,
                    "file": rel_path,
                    "line": i,
                    "type": "sources",
                })

    # ─── Pass 3: Extract call edges within function bodies ────────

    for node_id, (start, end) in fn_ranges.items():
        for li in range(start - 1, end):
            if li >= len(lines):
                break
            line = lines[li]
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            line_num = li + 1

            # Direct function calls: name(
            for m in re.finditer(r'\b([a-zA-Z_.][a-zA-Z0-9_.]*)\s*\(', stripped):
                call_name = m.group(1)
                if call_name in _R_KEYWORDS:
                    continue
                # Skip if it's the function being defined on this line
                if call_name == _node_fn_by_id(nodes, node_id):
                    continue
                # Skip common non-interesting patterns
                if call_name in ('function', 'if', 'for', 'while', 'switch'):
                    continue
                edges.append({
                    "from": node_id,
                    "to": call_name,
                    "file": rel_path,
                    "line": line_num,
                    "type": "calls",
                })

            # Namespace-qualified calls: pkg::fun(
            for m in re.finditer(r'\b([a-zA-Z][a-zA-Z0-9._]*)\s*:::?([a-zA-Z_.][a-zA-Z0-9_.]*)\s*\(', stripped):
                pkg_name = m.group(1)
                fn_name = m.group(2)
                edges.append({
                    "from": node_id,
                    "to": f"{pkg_name}::{fn_name}",
                    "file": rel_path,
                    "line": line_num,
                    "type": "calls",
                })

            # Method calls on objects: obj$method(
            for m in re.finditer(r'\$(\w+)\s*\(', stripped):
                method_name = m.group(1)
                if method_name not in _R_KEYWORDS:
                    edges.append({
                        "from": node_id,
                        "to": method_name,
                        "file": rel_path,
                        "line": line_num,
                        "type": "calls",
                        "via_dollar": True,
                    })

    # ─── Pass 4: Pipe operator detection ───────────────────────────

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Detect pipe chains: %>% or |>
        has_pipe = bool(re.search(r'%>%|\|>', stripped))
        if not has_pipe:
            continue

        owner_node = _find_owner_node(nodes, i, fn_ranges)

        # Extract all function calls in the pipe chain
        # Pattern: %>% fun(...) or |> fun(...)
        for m in re.finditer(r'(?:%>%|\|>)\s*([a-zA-Z_.][a-zA-Z0-9_.]*)\s*\(', stripped):
            pipe_fn = m.group(1)
            if pipe_fn in _R_KEYWORDS:
                continue
            from_id = owner_node["id"] if owner_node else rel_path
            edges.append({
                "from": from_id,
                "to": pipe_fn,
                "file": rel_path,
                "line": i,
                "type": "calls",
                "via_pipe": True,
            })

        # Also detect pkg::fun in pipe chains
        for m in re.finditer(r'(?:%>%|\|>)\s*([a-zA-Z][a-zA-Z0-9._]*)\s*:::?([a-zA-Z_.][a-zA-Z0-9_.]*)\s*\(', stripped):
            pkg_name = m.group(1)
            fn_name = m.group(2)
            from_id = owner_node["id"] if owner_node else rel_path
            edges.append({
                "from": from_id,
                "to": f"{pkg_name}::{fn_name}",
                "file": rel_path,
                "line": i,
                "type": "calls",
                "via_pipe": True,
            })

    # ─── Pass 5: Shiny-specific patterns ──────────────────────────

    _SHINY_REACTIVES = re.compile(
        r'\b(observeEvent|observe|reactive|reactiveVal|eventReactive|'
        r'renderPlot|renderTable|renderText|renderUI|renderImage|renderPrint|'
        r'renderDataTable|renderSvg)\s*\('
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        owner_node = _find_owner_node(nodes, i, fn_ranges)

        # Shiny reactive/render calls
        for m in _SHINY_REACTIVES.finditer(stripped):
            reactive_fn = m.group(1)
            from_id = owner_node["id"] if owner_node else rel_path
            edges.append({
                "from": from_id,
                "to": reactive_fn,
                "file": rel_path,
                "line": i,
                "type": "calls",
                "shiny": True,
            })

        # input$xxx and output$xxx references
        for m in re.finditer(r'\binput\$(\w+)', stripped):
            input_name = m.group(1)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to": f"input${input_name}",
                    "file": rel_path,
                    "line": i,
                    "type": "calls",
                    "shiny_input": True,
                })

        for m in re.finditer(r'\boutput\$(\w+)', stripped):
            output_name = m.group(1)
            if owner_node:
                edges.append({
                    "from": owner_node["id"],
                    "to": f"output${output_name}",
                    "file": rel_path,
                    "line": i,
                    "type": "calls",
                    "shiny_output": True,
                })

    return {"nodes": nodes, "edges": edges}


# ─── Helper functions ──────────────────────────────────────────────


def _find_owner_node(nodes: List[Dict[str, Any]], line_num: int, fn_ranges: Optional[Dict[str, tuple]] = None) -> Optional[Dict[str, Any]]:
    """Find the nearest preceding function/class node that 'owns' a given line.

    If fn_ranges is provided, uses body ranges for accurate scoping.
    Otherwise, falls back to nearest-preceding heuristic.
    """
    if fn_ranges:
        # Use body ranges: a line belongs to a node if it's within [start, end]
        best = None
        for node in nodes:
            n_line = node.get("line", 0)
            if node.get("type") not in ("function", "s3_method", "s4_class", "r6_class"):
                continue
            nid = node.get("id", "")
            rng = fn_ranges.get(nid)
            if rng and rng[0] <= line_num <= rng[1]:
                if best is None or n_line > best.get("line", 0):
                    best = node
        # Fall back to nearest preceding if no range contains the line
        if best is None:
            for node in nodes:
                n_line = node.get("line", 0)
                if n_line <= line_num:
                    if node.get("type") in ("function", "s3_method", "s4_class", "r6_class"):
                        if best is None or n_line > best.get("line", 0):
                            best = node
        return best

    # Simple heuristic: nearest preceding function-like node
    best = None
    for node in nodes:
        n_line = node.get("line", 0)
        if n_line <= line_num:
            if node.get("type") in ("function", "s3_method", "s4_class", "r6_class"):
                if best is None or n_line > best.get("line", 0):
                    best = node
    return best


def _node_fn_by_id(nodes: List[Dict[str, Any]], node_id: str) -> Optional[str]:
    """Get the fn (function name) for a given node id."""
    for node in nodes:
        if node.get("id") == node_id:
            return node.get("fn")
    return None


def _build_fn_ranges(lines: List[str], nodes: List[Dict[str, Any]]) -> Dict[str, tuple]:
    """Build a mapping of function node_id → (start_line, end_line).

    Uses brace-counting heuristics to determine function body extent.
    R functions are typically single-line or brace-delimited, e.g.:
        my_fun <- function(x) {
          ...
        }
    """
    fn_ranges: Dict[str, tuple] = {}

    # Collect only function-like nodes, sorted by line
    fn_nodes = sorted(
        [n for n in nodes if n.get("type") in ("function", "s3_method")],
        key=lambda n: n.get("line", 0),
    )

    for idx, node in enumerate(fn_nodes):
        start = node.get("line", 0)
        if start == 0:
            continue

        # Look for the opening brace on this line or the next few lines
        brace_found = False
        brace_line = start
        for offset in range(0, 4):
            check = start - 1 + offset
            if check >= len(lines):
                break
            if '{' in lines[check]:
                brace_found = True
                brace_line = check + 1
                break

        if not brace_found:
            # Single-line function or non-braced function
            # Assign just this line as the body
            fn_ranges[node["id"]] = (start, start)
            continue

        # Count braces from brace_line to find the end
        depth = 0
        end_line = len(lines)
        for li in range(brace_line - 1, len(lines)):
            line = lines[li]
            # Skip string contents naively (count braces outside strings)
            depth += line.count('{') - line.count('}')
            if depth <= 0:
                end_line = li + 1
                break

        # Ensure no overlap with next function
        if idx + 1 < len(fn_nodes):
            next_start = fn_nodes[idx + 1].get("line", 0)
            if end_line > next_start:
                end_line = next_start

        fn_ranges[node["id"]] = (start, end_line)

    return fn_ranges

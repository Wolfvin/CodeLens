"""
Fallback Haskell Parser for CodeLens — regex-based extraction.
Extracts modules, functions, type signatures, data types, newtypes, type aliases,
type classes, instances, type families, GADTs, deriving clauses, imports,
and function call relationships for edge resolution.
Supports: .hs and .lhs files.
"""

import re
from typing import Dict, List, Any, Set, Tuple


def _strip_comments(content: str) -> str:
    """Remove Haskell comments from source for cleaner regex matching.

    Handles:
      - Line comments: -- ...
      - Block comments: {- ... -}  (including nested)
      - Pragmas are preserved ({-# ... #-})
    """
    result = []
    i = 0
    n = len(content)
    while i < n:
        # Pragma: keep it
        if content[i:i + 3] == '{-#':
            end = content.find('#-}', i + 3)
            if end != -1:
                result.append(content[i:end + 3])
                i = end + 3
            else:
                result.append(content[i:])
                break
        # Block comment: {- ... -}
        elif content[i:i + 2] == '{-':
            depth = 1
            j = i + 2
            while j < n - 1 and depth > 0:
                if content[j:j + 2] == '{-':
                    depth += 1
                    j += 2
                elif content[j:j + 2] == '-}':
                    depth -= 1
                    j += 2
                else:
                    j += 1
            # Replace comment with whitespace to preserve line numbers
            chunk = content[i:j]
            result.append('\n' * chunk.count('\n'))
            i = j
        # Line comment: --
        elif content[i:i + 2] == '--':
            end = content.find('\n', i)
            if end == -1:
                i = n
            else:
                result.append('\n')
                i = end + 1
        else:
            result.append(content[i])
            i += 1
    return ''.join(result)


def _is_toplevel(line: str) -> bool:
    """Return True if the line starts at column 0 (top-level declaration)."""
    return len(line) > 0 and not line[0].isspace()


def parse_haskell_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Haskell source using regex — extracts definitions, imports, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    clean = _strip_comments(content)
    lines = clean.split('\n')

    # ─── Haskell keywords & builtins to skip when resolving calls ──────
    _HASKELL_KEYWORDS: Set[str] = frozenset({
        'module', 'where', 'import', 'qualified', 'as', 'hiding',
        'data', 'newtype', 'type', 'class', 'instance', 'deriving',
        'if', 'then', 'else', 'case', 'of', 'let', 'in', 'do',
        'forall', 'family', 'stock', 'anyclass',
        'infixl', 'infixr', 'infix',
        'default', 'foreign', 'safe', 'unsafe', 'rec', 'proc',
        'via',
    })

    _HASKELL_BUILTINS: Set[str] = frozenset({
        'True', 'False', 'Nothing', 'Just', 'Left', 'Right',
        'LT', 'EQ', 'GT',
        'map', 'filter', 'foldl', 'foldr', 'fmap', 'return', 'pure',
        'putStrLn', 'putStr', 'print', 'getLine', 'getContents',
        'read', 'show', 'error', 'undefined', 'seq', 'id', 'const',
        'head', 'tail', 'init', 'last', 'length', 'null',
        'take', 'drop', 'splitAt', 'zip', 'unzip', 'zipWith',
        'concat', 'concatMap', 'sum', 'product', 'minimum', 'maximum',
        'elem', 'notElem', 'reverse', 'and', 'or', 'any', 'all',
        'maybe', 'either', 'fromMaybe', 'fromIntegral', 'realToFrac',
        'fst', 'snd', 'curry', 'uncurry', 'flip', 'until',
        'putChar', 'getChar', 'readFile', 'writeFile', 'appendFile',
        'lines', 'unlines', 'words', 'unwords',
        'IO', 'Maybe', 'Either', 'Bool', 'Int', 'Integer', 'Float',
        'Double', 'Char', 'String', 'Show', 'Eq', 'Ord', 'Enum',
        'Bounded', 'Num', 'Real', 'Integral', 'Fractional',
        'Functor', 'Applicative', 'Monad', 'Monoid', 'Semigroup',
        'Foldable', 'Traversable', 'Read',
        'putMVar', 'takeMVar', 'forkIO', 'threadDelay',
        'MonadIO', 'MonadReader', 'MonadState', 'MonadWriter',
        'liftIO', 'ask', 'get', 'put', 'tell', 'runReaderT',
        'lift', 'when', 'unless', 'void', 'forever', 'join',
        'mapM', 'mapM_', 'forM', 'forM_', 'sequence', 'sequence_',
        'replicateM', 'replicateM_', 'foldM', 'foldM_',
        'succ', 'pred', 'minBound', 'maxBound', 'toEnum', 'fromEnum',
        'div', 'mod', 'quot', 'rem', 'gcd', 'lcm', 'abs', 'signum',
        'negate', 'recip', 'pi', 'exp', 'log', 'sqrt', 'sin', 'cos',
        'tan', 'asin', 'acos', 'atan', 'not',
        'round', 'floor', 'ceiling', 'truncate',
        'lookup', 'iterate', 'repeat', 'cycle', 'scanl', 'scanr',
        'isNothing', 'isJust', 'fromJust', 'catMaybes',
        'mapMaybe', 'partition', 'sort', 'sortBy', 'group', 'groupBy',
        'nub', 'delete', 'union', 'intersect',
        'readMaybe', 'readEither',
    })

    # ─── Collect definitions ────────────────────────────────────────────
    fn_defs: Dict[str, str] = {}        # fn_name → node_id
    type_defs: Dict[str, str] = {}      # type_name → node_id
    class_defs: Dict[str, str] = {}     # class_name → node_id
    instance_defs: Dict[str, str] = {}  # "ClassName_TypeName" → node_id

    # Track which lines are inside class/instance bodies (indented)
    class_instance_lines: Set[int] = set()

    # ─── 1. Module declarations ─────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*module\s+([\w.]+)\s*(?:\(.*?\))?\s*where', line)
        if m:
            mod_name = m.group(1)
            node_id = f"{rel_path}:{i}:module_{mod_name}"
            nodes.append({
                "id": node_id, "type": "module",
                "name": mod_name, "fn": mod_name,
                "file": rel_path, "line": i,
            })
            break

    # ─── 2. Imports ─────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(
            r'\s*import\s+(?:qualified\s+)?([\w.]+)'
            r'(?:\s+as\s+(\w+))?'
            r'(?:\s+hiding\s*\([^)]*\))?'
            r'(?:\s*\([^)]*\))?',
            line,
        )
        if m:
            imported_module = m.group(1)
            alias = m.group(2)
            edges.append({
                "from": rel_path,
                "to": imported_module,
                "to_fn": imported_module,
                "file": rel_path,
                "line": i,
                "type": "imports",
                "weight": 1,
            })
            if alias:
                edges.append({
                    "from": rel_path,
                    "to": imported_module,
                    "to_fn": f"{imported_module} as {alias}",
                    "file": rel_path,
                    "line": i,
                    "type": "imports",
                    "weight": 1,
                })

    # ─── 3. Type families ───────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        m = re.match(r'type\s+family\s+(\w+)', line)
        if m:
            tf_name = m.group(1)
            node_id = f"{rel_path}:{i}:typefamily_{tf_name}"
            nodes.append({
                "id": node_id, "type": "type_alias",
                "name": tf_name, "fn": tf_name,
                "file": rel_path, "line": i,
            })
            type_defs[tf_name] = node_id

    # ─── 4. Type aliases ────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        m = re.match(r'type\s+(\w+)\s*=', line)
        if m:
            if re.match(r'type\s+family\s+', line):
                continue
            type_name = m.group(1)
            if type_name[0].isupper():
                node_id = f"{rel_path}:{i}:type_{type_name}"
                nodes.append({
                    "id": node_id, "type": "type_alias",
                    "name": type_name, "fn": type_name,
                    "file": rel_path, "line": i,
                })
                type_defs[type_name] = node_id

    # ─── 5. Data types & GADTs ──────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        # GADT: data TypeName where
        m = re.match(r'data\s+(\w+).*\bwhere\s*$', line)
        if m:
            data_name = m.group(1)
            node_id = f"{rel_path}:{i}:data_{data_name}"
            nodes.append({
                "id": node_id, "type": "data_type",
                "name": data_name, "fn": data_name,
                "file": rel_path, "line": i,
                "gadt": True,
            })
            type_defs[data_name] = node_id
            _extract_deriving(line, node_id, rel_path, i, edges)
            continue

        # Regular data: data TypeName = ... | ...
        m = re.match(r'data\s+(\w+)', line)
        if m:
            data_name = m.group(1)
            node_id = f"{rel_path}:{i}:data_{data_name}"
            nodes.append({
                "id": node_id, "type": "data_type",
                "name": data_name, "fn": data_name,
                "file": rel_path, "line": i,
            })
            type_defs[data_name] = node_id
            _extract_deriving(line, node_id, rel_path, i, edges)

    # ─── 6. Newtype ─────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        m = re.match(r'newtype\s+(\w+)', line)
        if m:
            nt_name = m.group(1)
            node_id = f"{rel_path}:{i}:newtype_{nt_name}"
            nodes.append({
                "id": node_id, "type": "newtype",
                "name": nt_name, "fn": nt_name,
                "file": rel_path, "line": i,
            })
            type_defs[nt_name] = node_id
            _extract_deriving(line, node_id, rel_path, i, edges)

    # ─── 6b. Deriving on separate lines ─────────────────────────────────
    # IMPORTANT: This must run AFTER both data and newtype sections so that
    # _find_preceding_type_node can see all type definition nodes.
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Handle: } deriving (C1, C2, ...)  or  deriving (C1, C2, ...)
        m = re.match(
            r'\s*\}?\s*deriving\s+(?:stock\s+|anyclass\s+|newtype\s+)?\(([^)]+)\)\s*$',
            line,
        )
        if m:
            classes = re.findall(r'(\w+)', m.group(1))
            parent_node = _find_preceding_type_node(nodes, i)
            if parent_node:
                for cls in classes:
                    if cls[0].isupper():
                        edges.append({
                            "from": parent_node["id"], "to_fn": cls,
                            "file": rel_path, "line": i,
                            "type": "derives",
                        })
            continue

        # Handle: deriving ClassName  (single class without parens)
        m = re.match(
            r'\s*\}?\s*deriving\s+(stock\s+|anyclass\s+|newtype\s+)?(\w+)\s*$',
            line,
        )
        if m:
            cls = m.group(2)
            if cls[0].isupper():
                parent_node = _find_preceding_type_node(nodes, i)
                if parent_node:
                    edges.append({
                        "from": parent_node["id"], "to_fn": cls,
                        "file": rel_path, "line": i,
                        "type": "derives",
                    })
            continue

        # Deriving via: deriving via VClassName (C1, C2) for Type
        m = re.match(r'\s*deriving\s+via\s+(\w+).*?\(([^)]+)\)', line)
        if m:
            classes = re.findall(r'(\w+)', m.group(2))
            parent_node = _find_preceding_type_node(nodes, i)
            if parent_node:
                for cls in classes:
                    if cls[0].isupper():
                        edges.append({
                            "from": parent_node["id"], "to_fn": cls,
                            "file": rel_path, "line": i,
                            "type": "derives",
                        })

    # ─── 7. Type classes ────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        # class ClassName a where
        # class (SuperClass a) => ClassName a where
        m = re.match(r'class\s+(?:\([^)]+\)\s+=>\s+)?(\w+)\s+', line)
        if m:
            class_name = m.group(1)
            if class_name[0].isupper():
                node_id = f"{rel_path}:{i}:class_{class_name}"
                nodes.append({
                    "id": node_id, "type": "typeclass",
                    "name": class_name, "fn": class_name,
                    "file": rel_path, "line": i,
                })
                class_defs[class_name] = node_id
                # Mark indented lines as being inside this class body
                for j in range(i, len(lines)):
                    if j + 1 > i and _is_toplevel(lines[j]):
                        break
                    class_instance_lines.add(j + 1)
                # Check for superclass constraint
                sc = re.match(r'\s*class\s+\(([^)]+)\)\s+=>\s+', line)
                if sc:
                    for parent_cls in re.findall(r'(\w+)\s+\w+', sc.group(1)):
                        if parent_cls[0].isupper():
                            edges.append({
                                "from": node_id, "to_fn": parent_cls,
                                "file": rel_path, "line": i,
                                "type": "implements",
                            })

    # ─── 8. Type class instances ────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if not _is_toplevel(line):
            continue
        # instance ClassName Type where
        # instance (Constraint) => ClassName Type where
        m = re.match(
            r'instance\s+(?:\([^)]+\)\s+=>\s+)?(\w+)\s+([\w()[\]., ]+?)(?:\s+where)?\s*$',
            line,
        )
        if m:
            class_name = m.group(1)
            type_part = m.group(2).strip().split()[0] if m.group(2) else ""
            if class_name[0].isupper():
                inst_key = f"{class_name}_{type_part}" if type_part else class_name
                node_id = f"{rel_path}:{i}:instance_{inst_key}"
                nodes.append({
                    "id": node_id, "type": "instance",
                    "name": f"{class_name} {m.group(2).strip()}" if m.group(2) else class_name,
                    "fn": f"{class_name} {type_part}".strip() if type_part else class_name,
                    "file": rel_path, "line": i,
                })
                instance_defs[inst_key] = node_id
                # Mark indented lines as being inside this instance body
                for j in range(i, len(lines)):
                    if j + 1 > i and _is_toplevel(lines[j]):
                        break
                    class_instance_lines.add(j + 1)
                # Edge: instance implements class
                if class_name in class_defs:
                    edges.append({
                        "from": node_id,
                        "to": class_defs[class_name],
                        "to_fn": class_name,
                        "file": rel_path,
                        "line": i,
                        "type": "implements",
                    })
                else:
                    edges.append({
                        "from": node_id,
                        "to_fn": class_name,
                        "file": rel_path,
                        "line": i,
                        "type": "implements",
                    })
                # Edge: instance mentions a type
                if type_part and type_part[0].isupper() and type_part in type_defs:
                    edges.append({
                        "from": node_id,
                        "to": type_defs[type_part],
                        "to_fn": type_part,
                        "file": rel_path,
                        "line": i,
                        "type": "implements",
                    })

    # ─── 9. Type signatures (top-level only) ────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if i in class_instance_lines:
            continue
        if not _is_toplevel(line):
            continue

        # Operator type signature: (.$) :: Type
        m = re.match(r'\(([-+*/=<>:,.$|\\~&%^!#@?]+)\)\s+::', stripped)
        if m:
            op_name = m.group(1)
            node_id = f"{rel_path}:{i}:op_{op_name}"
            nodes.append({
                "id": node_id, "type": "function",
                "name": f"({op_name})", "fn": f"({op_name})",
                "file": rel_path, "line": i,
                "operator": True,
            })
            fn_defs[f"({op_name})"] = node_id
            continue

        # Regular type signature: functionName :: Type
        m = re.match(r'([a-z_][\w\']*)\s+::', stripped)
        if m:
            fn_name = m.group(1)
            if fn_name in _HASKELL_KEYWORDS:
                continue
            if fn_name not in fn_defs:
                node_id = f"{rel_path}:{i}:fn_{fn_name}"
                nodes.append({
                    "id": node_id, "type": "function",
                    "name": fn_name, "fn": fn_name,
                    "file": rel_path, "line": i,
                })
                fn_defs[fn_name] = node_id
            continue

    # ─── 10. Function definitions (top-level only) ──────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if i in class_instance_lines:
            continue
        if not _is_toplevel(line):
            continue

        # Function definition: name params = body
        m = re.match(r'([a-z_][\w\']*)\s+[\w' + re.escape("()[]{},\"`_") + r']*\s*=\s*', stripped)
        if m:
            fn_name = m.group(1)
            if fn_name in _HASKELL_KEYWORDS:
                continue
            if fn_name not in fn_defs:
                node_id = f"{rel_path}:{i}:fn_{fn_name}"
                nodes.append({
                    "id": node_id, "type": "function",
                    "name": fn_name, "fn": fn_name,
                    "file": rel_path, "line": i,
                })
                fn_defs[fn_name] = node_id
            continue

        # Nullary definition: name = body
        m = re.match(r'([a-z_][\w\']*)\s*=\s*', stripped)
        if m:
            fn_name = m.group(1)
            if fn_name in _HASKELL_KEYWORDS:
                continue
            if fn_name not in fn_defs:
                node_id = f"{rel_path}:{i}:fn_{fn_name}"
                nodes.append({
                    "id": node_id, "type": "function",
                    "name": fn_name, "fn": fn_name,
                    "file": rel_path, "line": i,
                })
                fn_defs[fn_name] = node_id
            continue

        # Operator definition: (.$) x y = body
        m = re.match(r'\(([-+*/=<>:,.$|\\~&%^!#@?]+)\)\s+.*=\s*', stripped)
        if m:
            op_name = m.group(1)
            fn_key = f"({op_name})"
            if fn_key not in fn_defs:
                node_id = f"{rel_path}:{i}:op_{op_name}"
                nodes.append({
                    "id": node_id, "type": "function",
                    "name": fn_key, "fn": fn_key,
                    "file": rel_path, "line": i,
                    "operator": True,
                })
                fn_defs[fn_key] = node_id

    # ─── 11. Call edges from function bodies ────────────────────────────
    # Build function → body range map using indentation
    # We pass lines so we can find the actual definition lines (with =)
    fn_ranges = _build_fn_ranges(lines, nodes, fn_defs)

    # Patterns for extracting function calls from bodies
    qualified_call = re.compile(r'\b([A-Z][\w.]*)\.([a-z_][\w\']*)\b')
    backtick_call = re.compile(r'`([a-z_][\w\']*)`')
    # Lowercase identifiers that could be function calls
    call_ident = re.compile(r'(?<!\.)(?<!\w)([a-z_][\w\']*)\b')
    # Uppercase identifiers that could be constructors
    upper_call = re.compile(r'(?<![.\w])([A-Z]\w*)\b')

    # Build a reverse map: node_id → fn_name
    node_to_name: Dict[str, str] = {v: k for k, v in fn_defs.items()}

    for fn_id, start_line, end_line in fn_ranges:
        fn_name = node_to_name.get(fn_id, "")

        # Collect the expression parts of each body line (skip definition patterns)
        expr_lines: List[str] = []
        # Also collect parameter / binding names to filter out
        local_names: Set[str] = set()

        for line_no in range(max(1, start_line), end_line + 1):
            raw_line = lines[line_no - 1]  # 0-indexed
            stripped = raw_line.strip()
            if not stripped:
                continue

            # Extract local binding names from do-notation: x <- action
            bind_m = re.match(r'([a-z_][\w\']*)\s*<-\s*', stripped)
            if bind_m:
                local_names.add(bind_m.group(1))

            # Extract local binding names from let: let x = ...
            let_m = re.search(r'\blet\s+([a-z_][\w\']*)\s*=', stripped)
            if let_m:
                local_names.add(let_m.group(1))

            # For lines containing '=', extract the expression part (right side)
            # and any local bindings (left side parameters)
            eq_pos = _find_expression_start(stripped, fn_name)
            if eq_pos is not None:
                pattern_part = stripped[:eq_pos]
                expr_part = stripped[eq_pos:]
                # Only extract parameter names from lines that define the
                # current function (pattern-match alternatives), NOT from
                # where-clause local function definitions
                if _line_is_fn_alternative(stripped, fn_name):
                    _extract_pattern_names(pattern_part, fn_name, local_names)
                else:
                    # For local definitions (where clause), still extract
                    # the names between the local fn name and '=' as params
                    # of that local fn, so they don't appear as calls
                    local_fn_m = re.match(r'([a-z_][\w\']*)\s', pattern_part)
                    if local_fn_m:
                        local_fn_name = local_fn_m.group(1)
                        _extract_pattern_names(pattern_part, local_fn_name, local_names)
                expr_lines.append(expr_part)
            else:
                # Continuation line (no '=' found) — entire line is expression
                expr_lines.append(stripped)

        body = '\n'.join(expr_lines)

        called: Set[str] = set()

        # Qualified calls: Module.function
        for m in qualified_call.finditer(body):
            mod_part = m.group(1)
            callee = m.group(2)
            if callee not in _HASKELL_KEYWORDS and callee not in _HASKELL_BUILTINS:
                if len(callee) > 1 and callee not in local_names:
                    called.add(callee)

        # Backtick infix calls: x `f` y
        for m in backtick_call.finditer(body):
            callee = m.group(1)
            if callee not in _HASKELL_KEYWORDS and callee not in _HASKELL_BUILTINS:
                if len(callee) > 1 and callee not in local_names:
                    called.add(callee)

        # Regular function application (lowercase identifiers)
        for m in call_ident.finditer(body):
            callee = m.group(1)
            if callee in _HASKELL_KEYWORDS or callee in _HASKELL_BUILTINS:
                continue
            if len(callee) <= 1:
                continue
            if callee in local_names:
                continue
            called.add(callee)

        # Constructor calls and type-class method calls (uppercase identifiers)
        for m in upper_call.finditer(body):
            name = m.group(1)
            if name in _HASKELL_BUILTINS:
                continue
            if len(name) <= 1:
                continue
            if name in type_defs or name in class_defs:
                called.add(name)

        # Emit edges for each unique callee
        for callee in sorted(called):
            if callee in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[callee],
                    "to_fn": callee,
                    "file": rel_path,
                    "line": start_line,
                    "type": "calls",
                })
            elif callee in type_defs:
                edges.append({
                    "from": fn_id,
                    "to": type_defs[callee],
                    "to_fn": callee,
                    "file": rel_path,
                    "line": start_line,
                    "type": "calls",
                })
            elif callee in class_defs:
                edges.append({
                    "from": fn_id,
                    "to": class_defs[callee],
                    "to_fn": callee,
                    "file": rel_path,
                    "line": start_line,
                    "type": "calls",
                })
            else:
                edges.append({
                    "from": fn_id,
                    "to_fn": callee,
                    "file": rel_path,
                    "line": start_line,
                    "type": "calls",
                })

    return {"nodes": nodes, "edges": edges}


# ─── Helper: extract deriving clauses from a single line ────────────────
def _extract_deriving(
    line: str, node_id: str, rel_path: str, line_no: int,
    edges: List[Dict[str, Any]],
) -> None:
    """Extract deriving clauses from a data/newtype declaration line."""
    # deriving (C1, C2, ...)
    dm = re.search(
        r'\bderiving\s+(?:stock\s+|anyclass\s+|newtype\s+)?\(([^)]+)\)', line
    )
    if dm:
        for cls in re.findall(r'(\w+)', dm.group(1)):
            if cls[0].isupper():
                edges.append({
                    "from": node_id, "to_fn": cls,
                    "file": rel_path, "line": line_no,
                    "type": "derives",
                })
        return
    # deriving ClassName (single class, no parens)
    dm2 = re.search(r'\bderiving\s+(stock\s+|anyclass\s+|newtype\s+)?(\w+)\s*$', line)
    if dm2:
        cls = dm2.group(2)
        if cls[0].isupper():
            edges.append({
                "from": node_id, "to_fn": cls,
                "file": rel_path, "line": line_no,
                "type": "derives",
            })


# ─── Helper: find the closest preceding data/newtype node for deriving ──
def _find_preceding_type_node(
    nodes: List[Dict[str, Any]], line: int
) -> Dict[str, Any] | None:
    """Find the nearest preceding data_type or newtype node."""
    best = None
    best_line = 0
    for node in nodes:
        if node.get("type") in ("data_type", "newtype"):
            nline = node.get("line", 0)
            if nline < line and nline > best_line:
                best = node
                best_line = nline
    return best


# ─── Helper: build function body ranges from indentation ────────────────
def _build_fn_ranges(
    lines: List[str],
    nodes: List[Dict[str, Any]],
    fn_defs: Dict[str, str],
) -> List[Tuple[str, int, int]]:
    """Determine (node_id, start_line, end_line) for each function body.

    Strategy:
      1. Identify function nodes and find their actual definition lines
         (the ones with '=' not just type signatures with '::').
      2. For each function, its body extends from its definition line to
         the line just before the next top-level declaration.
      3. Pattern-match alternatives at indent=0 that start with the same
         function name are included in the same body.
      4. Type signature lines are excluded from the body (they don't contain
         executable code, only type annotations).
    """
    if not fn_defs:
        return []

    # Build a reverse map: node_id → fn_name
    node_to_name: Dict[str, str] = {}
    for fn_name, node_id in fn_defs.items():
        node_to_name[node_id] = fn_name

    # For each function node, find its definition line (the one with '=')
    # and collect all body lines (definition + indented continuation lines,
    # plus pattern-match alternatives at indent=0 with the same name)
    fn_def_lines: Dict[int, str] = {}  # definition_line → node_id

    for node in nodes:
        if node.get("type") != "function":
            continue
        node_id = node["id"]
        if node_id not in node_to_name:
            continue
        fn_name = node_to_name[node_id]
        sig_line = node["line"]

        # Find the actual definition line (with '=') starting from the
        # type signature line
        def_line = sig_line
        for j in range(sig_line, len(lines) + 1):
            line = lines[j - 1]  # 0-indexed
            stripped = line.strip()
            if not stripped:
                continue
            # Check for type signature (skip it)
            if '::' in stripped and re.match(r'[a-z_][\w\']*\s+::', stripped):
                continue
            # Check for function definition with this name
            if re.match(rf'^{re.escape(fn_name)}\b', stripped) and '=' in stripped:
                def_line = j
                break
            # Check for operator definition
            if fn_name.startswith('(') and fn_name.endswith(')'):
                op_inner = fn_name[1:-1]
                if re.match(rf'^\({re.escape(op_inner)}\)', stripped) and '=' in stripped:
                    def_line = j
                    break
            # If we hit another top-level declaration, stop looking
            if _is_toplevel(line) and j > sig_line:
                break

        fn_def_lines[def_line] = node_id

    if not fn_def_lines:
        return []

    # For each function definition, determine the body range
    sorted_def_lines = sorted(fn_def_lines.keys())
    ranges: List[Tuple[str, int, int]] = []

    for idx, start in enumerate(sorted_def_lines):
        fn_id = fn_def_lines[start]
        fn_name = node_to_name.get(fn_id, "")

        # The body extends until the next top-level line that is NOT
        # a pattern-match alternative for the same function
        end = len(lines)
        for j in range(start + 1, len(lines) + 1):
            line = lines[j - 1]  # 0-indexed
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                # Check if this is a pattern-match alternative for the same function
                if fn_name and re.match(rf'^{re.escape(fn_name)}\b', stripped):
                    continue  # Same function, different pattern
                # This is a new top-level declaration
                end = j - 1
                break
        ranges.append((fn_id, start, end))

    return ranges


# ─── Helper: find where the expression part starts in a line ─────────────
def _find_expression_start(line: str, fn_name: str) -> int | None:
    """Find the position of the first '=' that separates pattern from expression.

    Returns the index of the character AFTER the '=', or None if no suitable
    '=' is found.  Skips '=' inside parentheses, brackets, and type signatures.
    """
    # Skip type signatures entirely
    if '::' in line:
        sig_m = re.match(r'[a-z_][\w\']*\s+::', line)
        if sig_m:
            return None

    depth = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
        elif ch == '=' and depth == 0:
            # Make sure it's not '==' (comparison operator) or '=>' (type arrow)
            if i + 1 < n and line[i + 1] in '=>':
                i += 1
                continue
            # Make sure it's not '<=' (comparison)
            if i > 0 and line[i - 1] in '<!':
                i += 1
                continue
            # Make sure it's not '/=' (not equal)
            if i >= 1 and line[i - 1] == '/' and i >= 2 and line[i - 2] != '-':
                i += 1
                continue
            return i + 1  # Position after '='
        i += 1
    return None


# ─── Helper: extract local names from a pattern ─────────────────────────
def _extract_pattern_names(
    pattern_part: str, fn_name: str, local_names: Set[str]
) -> None:
    """Extract parameter and binding names from the left side of '='.

    These are names that should NOT be counted as function calls.
    """
    # Remove the function name from the beginning of the pattern
    cleaned = pattern_part
    if fn_name and fn_name.startswith('('):
        # Operator: remove (op) from the beginning
        cleaned = re.sub(r'^\([^)]+\)\s*', '', cleaned)
    elif fn_name:
        cleaned = re.sub(rf'^{re.escape(fn_name)}\b\s*', '', cleaned)

    # Extract lowercase identifiers (these are pattern variables / parameters)
    for m in re.finditer(r'\b([a-z_][\w\']*)\b', cleaned):
        name = m.group(1)
        # Skip Haskell keywords
        if name in ('where', 'let', 'in', 'do', 'case', 'of',
                     'if', 'then', 'else', 'rec', 'proc'):
            continue
        local_names.add(name)


# ─── Helper: check if a line is a pattern-match alternative for a function
def _line_is_fn_alternative(line: str, fn_name: str) -> bool:
    """Check if the stripped line is a definition of the given function.

    Handles both regular function names and operator names.
    """
    if not fn_name:
        return False
    if fn_name.startswith('(') and fn_name.endswith(')'):
        op_inner = fn_name[1:-1]
        return bool(re.match(rf'^\({re.escape(op_inner)}\)', line))
    return bool(re.match(rf'^{re.escape(fn_name)}\b', line))

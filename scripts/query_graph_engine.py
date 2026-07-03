# @WHO:   scripts/query_graph_engine.py
# @WHAT:  Cypher-subset graph query engine for MCP tool query_graph (issue #9)
# @PART:  engine
# @ENTRY: execute_query()
"""Cypher-subset graph query engine for CodeLens (issue #9).

Agents currently must chain multiple MCP tools (trace → impact → context) to
answer structural questions. Each hop costs tokens and round-trips. This
module implements a single expressive query language — an openCypher subset —
that replaces 3-5 tool calls with one.

Supported subset (MVP per issue #9 spec):
    MATCH (var:Label)-[:EDGE_TYPE]->(var2)
    WHERE var.property = 'value'
    WHERE var.name CONTAINS 'substr'
    WHERE var.file IS NULL
    WHERE NOT EXISTS { (other)-[:CALLS]->(var) }
    RETURN var.name, var2.file
    LIMIT 10

Grammar (informal):
    query    := MATCH pattern [WHERE predicate] [RETURN items] [LIMIT n]
    pattern  := node [edge node]*
    node     := ( [var] [:Label] )
    edge     := -[:EDGE_TYPE]-> | <-[:EDGE_TYPE]- | -[:EDGE_TYPE]-  (undirected)
    predicate:= expr (= | CONTAINS | IS NULL | IS NOT NULL)
              | NOT EXISTS { pattern }
              | predicate AND predicate
              | predicate OR predicate
    items    := * | var.property [, var.property]*

Design:
- **Read-only.** No CREATE/DELETE/MERGE — safe for CI.
- **Pure Python, zero deps.** No external Cypher library needed.
- **SQLite-backed.** Queries compile to SQL against graph_nodes + graph_edges.
- **Defensive.** Malformed queries return structured errors, not exceptions.
- **Backward-compatible.** New module; no existing command is touched.

Limitations (documented, not bugs):
- Single pattern per MATCH (no comma-separated multi-patterns in MVP).
- No WITH, ORDER BY, GROUP BY, aggregations, or subqueries beyond EXISTS.
- No string functions beyond CONTAINS.
- No variable-length paths (no `*` in edge). Use trace/impact for BFS.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from utils import default_db_path


# ─── Constants ─────────────────────────────────────────────────────────────

# Node properties that can be queried in WHERE / RETURN.
# Maps the Cypher property name to the SQLite column in graph_nodes.
_NODE_PROPERTIES = {
    "name": "name",
    "file": "file",
    "line": "line",
    "node_type": "node_type",
    "node_id": "node_id",
    "id": "id",
}

# Valid edge types (from graph_model.py).
_VALID_EDGE_TYPES = {
    "CALLS", "IMPORTS", "DEFINES", "INHERITS", "IMPLEMENTS", "USES_TYPE",
}

# Valid node labels (from graph_model.py).
_VALID_NODE_LABELS = {
    "function", "class", "file", "module", "route", "type", "interface",
}


# ─── Tokenizer ─────────────────────────────────────────────────────────────


class _Token:
    """A single token from the query lexer."""

    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind: str, value: str, pos: int):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, pos={self.pos})"


# Token kinds: KW (keyword), LPAREN, RPAREN, LBRACE, RBRACE, LBRACKET, RBRACKET,
# LARROW, RARROW, DASH, COLON, COMMA, DOT, STAR, IDENT, STRING, NUMBER, OP, EOF.
_KEYWORDS = frozenset({
    "MATCH", "WHERE", "RETURN", "LIMIT", "AND", "OR", "NOT",
    "EXISTS", "IS", "NULL", "CONTAINS", "TRUE", "FALSE",
})


def _tokenize(query: str) -> List[_Token]:
    """Lex the query string into tokens.

    Raises ``ValueError`` on unterminated strings or unknown characters.
    """
    tokens: List[_Token] = []
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]

        # Skip whitespace
        if ch.isspace():
            i += 1
            continue

        # Skip comments (-- ... end of line, Cypher-style)
        if ch == "-" and i + 1 < n and query[i + 1] == "-":
            while i < n and query[i] != "\n":
                i += 1
            continue

        # Single-char tokens
        if ch == "(":
            tokens.append(_Token("LPAREN", "(", i)); i += 1; continue
        if ch == ")":
            tokens.append(_Token("RPAREN", ")", i)); i += 1; continue
        if ch == "{":
            tokens.append(_Token("LBRACE", "{", i)); i += 1; continue
        if ch == "}":
            tokens.append(_Token("RBRACE", "}", i)); i += 1; continue
        if ch == "[":
            tokens.append(_Token("LBRACKET", "[", i)); i += 1; continue
        if ch == "]":
            tokens.append(_Token("RBRACKET", "]", i)); i += 1; continue
        if ch == ":":
            tokens.append(_Token("COLON", ":", i)); i += 1; continue
        if ch == ",":
            tokens.append(_Token("COMMA", ",", i)); i += 1; continue
        if ch == ".":
            tokens.append(_Token("DOT", ".", i)); i += 1; continue
        if ch == "*":
            tokens.append(_Token("STAR", "*", i)); i += 1; continue

        # Arrows and dashes (must check before OP because '-' is dash)
        if ch == "-" and i + 1 < n and query[i + 1] == ">":
            tokens.append(_Token("RARROW", "->", i)); i += 2; continue
        if ch == "<" and i + 1 < n and query[i + 1] == "-":
            tokens.append(_Token("LARROW", "<-", i)); i += 2; continue
        if ch == "-":
            tokens.append(_Token("DASH", "-", i)); i += 1; continue

        # Comparison operators
        if ch == "=":
            tokens.append(_Token("OP", "=", i)); i += 1; continue
        if ch == "!" and i + 1 < n and query[i + 1] == "=":
            tokens.append(_Token("OP", "!=", i)); i += 2; continue
        if ch == "<" and i + 1 < n and query[i + 1] == "=":
            tokens.append(_Token("OP", "<=", i)); i += 2; continue
        if ch == ">" and i + 1 < n and query[i + 1] == "=":
            tokens.append(_Token("OP", ">=", i)); i += 2; continue
        if ch == "<":
            tokens.append(_Token("OP", "<", i)); i += 1; continue
        if ch == ">":
            tokens.append(_Token("OP", ">", i)); i += 1; continue

        # Strings (single-quoted, Cypher-style)
        if ch == "'":
            j = i + 1
            while j < n and query[j] != "'":
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated string starting at position {i}")
            tokens.append(_Token("STRING", query[i + 1:j], i))
            i = j + 1
            continue
        # Double-quoted strings also accepted
        if ch == '"':
            j = i + 1
            while j < n and query[j] != '"':
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated string starting at position {i}")
            tokens.append(_Token("STRING", query[i + 1:j], i))
            i = j + 1
            continue

        # Numbers
        if ch.isdigit() or (ch == "-" and i + 1 < n and query[i + 1].isdigit()):
            j = i + 1
            while j < n and (query[j].isdigit() or query[j] == "."):
                j += 1
            tokens.append(_Token("NUMBER", query[i:j], i))
            i = j
            continue

        # Identifiers / keywords
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (query[j].isalnum() or query[j] == "_"):
                j += 1
            word = query[i:j]
            upper = word.upper()
            if upper in _KEYWORDS:
                tokens.append(_Token("KW", upper, i))
            else:
                tokens.append(_Token("IDENT", word, i))
            i = j
            continue

        raise ValueError(
            f"Unexpected character {ch!r} at position {i} in query"
        )

    tokens.append(_Token("EOF", "", i))
    return tokens


# ─── AST nodes ─────────────────────────────────────────────────────────────


class _NodePattern:
    """A node in a MATCH pattern: (var:Label)."""

    def __init__(self, var: Optional[str], label: Optional[str]):
        self.var = var
        self.label = label

    def __repr__(self):
        return f"NodePattern(var={self.var!r}, label={self.label!r})"


class _EdgePattern:
    """An edge in a MATCH pattern: -[:TYPE]->, <-[:TYPE]-, or -[:TYPE]-."""

    def __init__(self, edge_type: str, direction: str):
        # direction: "right" (->), "left" (<-), or "none" (-)
        self.edge_type = edge_type
        self.direction = direction

    def __repr__(self):
        return f"EdgePattern(type={self.edge_type!r}, dir={self.direction!r})"


class _Pattern:
    """A full MATCH pattern: node (edge node)*."""

    def __init__(self, nodes: List[_NodePattern], edges: List[_EdgePattern]):
        self.nodes = nodes
        self.edges = edges

    def __repr__(self):
        return f"Pattern(nodes={self.nodes}, edges={self.edges})"


class _Predicate:
    """Base class for WHERE predicates."""


class _PropertyPredicate(_Predicate):
    """var.property OP value | var.property IS [NOT] NULL | var.property CONTAINS value."""

    def __init__(self, var: str, prop: str, op: str, value: Any):
        self.var = var
        self.prop = prop
        self.op = op  # '=', '!=', '<', '>', '<=', '>=', 'CONTAINS', 'IS NULL', 'IS NOT NULL'
        self.value = value


class _NotExistsPredicate(_Predicate):
    """NOT EXISTS { pattern } — true when no matching path exists."""

    def __init__(self, pattern: _Pattern):
        self.pattern = pattern


class _BoolPredicate(_Predicate):
    """left AND/OR right."""

    def __init__(self, op: str, left: _Predicate, right: _Predicate):
        self.op = op  # 'AND' or 'OR'
        self.left = left
        self.right = right


class _Query:
    """A parsed Cypher-subset query."""

    def __init__(self):
        self.pattern: Optional[_Pattern] = None
        self.where: Optional[_Predicate] = None
        self.return_items: List[Tuple[str, Optional[str]]] = []  # (var, prop or None for *)
        self.return_star: bool = False
        self.limit: Optional[int] = None


# ─── Parser ────────────────────────────────────────────────────────────────


class _Parser:
    """Recursive-descent parser for the Cypher subset.

    Consumes a token list and produces a ``_Query`` AST. Raises
    ``ValueError`` with a human-readable message on syntax errors.
    """

    def __init__(self, tokens: List[_Token]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self, offset: int = 0) -> _Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]  # EOF
        return self.tokens[idx]

    def _advance(self) -> _Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _expect(self, kind: str, value: Optional[str] = None) -> _Token:
        tok = self._peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            expected = f"{kind}({value})" if value else kind
            raise ValueError(
                f"Expected {expected} but got {tok.kind}({tok.value!r}) "
                f"at position {tok.pos}"
            )
        return self._advance()

    def _match_kw(self, kw: str) -> bool:
        tok = self._peek()
        if tok.kind == "KW" and tok.value == kw:
            self._advance()
            return True
        return False

    def parse(self) -> _Query:
        q = _Query()

        # MATCH
        if not self._match_kw("MATCH"):
            raise ValueError("Query must start with MATCH")
        q.pattern = self._parse_pattern()

        # WHERE (optional)
        if self._match_kw("WHERE"):
            q.where = self._parse_predicate()

        # RETURN (optional — default to * if omitted)
        if self._match_kw("RETURN"):
            q.return_items, q.return_star = self._parse_return_items()
        else:
            q.return_star = True

        # LIMIT (optional)
        if self._match_kw("LIMIT"):
            tok = self._expect("NUMBER")
            q.limit = int(float(tok.value))
            if q.limit < 0:
                raise ValueError(f"LIMIT must be >= 0, got {q.limit}")

        # Should be at EOF
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise ValueError(
                f"Unexpected token {tok.kind}({tok.value!r}) at position {tok.pos} "
                f"— expected end of query"
            )

        return q

    def _parse_pattern(self) -> _Pattern:
        """Parse: node (edge node)*"""
        nodes = [self._parse_node()]
        edges = []
        while self._peek().kind in ("DASH", "LARROW"):
            edge = self._parse_edge()
            nodes.append(self._parse_node())
            edges.append(edge)
        return _Pattern(nodes, edges)

    def _parse_node(self) -> _NodePattern:
        """Parse: ( [var] [:Label] ) — bare () is an anonymous node (matches any)."""
        self._expect("LPAREN")
        var = None
        label = None
        if self._peek().kind == "IDENT":
            var = self._advance().value
        if self._peek().kind == "COLON":
            self._advance()
            label = self._expect("IDENT").value
        self._expect("RPAREN")
        # Bare () is valid — it's an anonymous node that matches any node.
        # No var or label needed.
        if label is not None:
            # Labels are case-insensitive — Cypher convention is PascalCase
            # (Function, Class) but graph_model stores lowercase. Normalize.
            label = label.lower()
            if label not in _VALID_NODE_LABELS:
                raise ValueError(
                    f"Unknown node label {label!r}. Valid: {sorted(_VALID_NODE_LABELS)}"
                )
        return _NodePattern(var, label)

    def _parse_edge(self) -> _EdgePattern:
        """Parse: -[:TYPE]-> | <-[:TYPE]- | -[:TYPE]- | -[:TYPE]->

        Standard Cypher edge syntax uses square brackets: -[:TYPE]->
        We also tolerate bare colon form (-:TYPE->) for robustness.
        """
        direction = "none"
        # Check for left arrow (<-)
        if self._peek().kind == "LARROW":
            self._advance()
            direction = "left"
        else:
            self._expect("DASH")

        # Optional [:TYPE] or :TYPE
        edge_type = None  # None means no type filter — match any edge
        if self._peek().kind == "LBRACKET":
            # Standard Cypher: -[:TYPE]->
            self._advance()
            if self._peek().kind == "COLON":
                self._advance()
                if self._peek().kind == "IDENT":
                    edge_type = self._advance().value.upper()
            self._expect("RBRACKET")
        elif self._peek().kind == "COLON":
            # Bare colon form: -:TYPE-> (tolerated, non-standard)
            self._advance()
            edge_type = self._expect("IDENT").value.upper()

        if edge_type is None:
            edge_type = "CALLS"  # default edge type when none specified

        if edge_type not in _VALID_EDGE_TYPES:
            raise ValueError(
                f"Unknown edge type {edge_type!r}. Valid: {sorted(_VALID_EDGE_TYPES)}"
            )

        # Closing dash or arrow
        if direction == "left":
            self._expect("DASH")
        else:
            if self._peek().kind == "RARROW":
                self._advance()
                direction = "right"
            else:
                self._expect("DASH")
                # undirected — direction stays "none"

        return _EdgePattern(edge_type, direction)

    def _parse_return_items(self) -> Tuple[List[Tuple[str, Optional[str]]], bool]:
        """Parse: * | var.property [, var.property]*"""
        if self._peek().kind == "STAR":
            self._advance()
            return [], True

        items: List[Tuple[str, Optional[str]]] = []
        while True:
            var = self._expect("IDENT").value
            prop = None
            if self._peek().kind == "DOT":
                self._advance()
                prop = self._expect("IDENT").value
            items.append((var, prop))
            if self._peek().kind != "COMMA":
                break
            self._advance()
        return items, False

    def _parse_predicate(self) -> _Predicate:
        """Parse a WHERE predicate with AND/OR (left-associative)."""
        left = self._parse_atom_predicate()
        while True:
            if self._match_kw("AND"):
                right = self._parse_atom_predicate()
                left = _BoolPredicate("AND", left, right)
            elif self._match_kw("OR"):
                right = self._parse_atom_predicate()
                left = _BoolPredicate("OR", left, right)
            else:
                break
        return left

    def _parse_atom_predicate(self) -> _Predicate:
        """Parse a single predicate: NOT EXISTS {...} | var.prop OP val | ..."""
        # NOT EXISTS { pattern }
        if self._match_kw("NOT"):
            if not self._match_kw("EXISTS"):
                raise ValueError("Expected EXISTS after NOT")
            self._expect("LBRACE")
            pattern = self._parse_pattern()
            self._expect("RBRACE")
            return _NotExistsPredicate(pattern)

        # EXISTS { pattern } (without NOT — returns true if path exists)
        # Per spec, we only need NOT EXISTS, but handle EXISTS too for completeness.
        if self._match_kw("EXISTS"):
            self._expect("LBRACE")
            pattern = self._parse_pattern()
            self._expect("RBRACE")
            # Wrap as NOT(NOT EXISTS) — reuse _NotExistsPredicate with inverted semantics
            # by negating at eval time. For simplicity, store as _NotExistsPredicate
            # with a flag. But spec only requires NOT EXISTS, so we implement EXISTS
            # as a synonym that returns true when matches found.
            # We'll store it as a special case: _NotExistsPredicate with negate=False.
            pred = _NotExistsPredicate(pattern)
            pred._exists_positive = True  # type: ignore[attr-defined]
            return pred

        # var.property OP value | var.property IS [NOT] NULL | var.property CONTAINS value
        var = self._expect("IDENT").value
        self._expect("DOT")
        prop = self._expect("IDENT").value

        tok = self._peek()
        if tok.kind == "KW" and tok.value == "IS":
            self._advance()
            negate = self._match_kw("NOT")
            if not self._match_kw("NULL"):
                raise ValueError("Expected NULL after IS [NOT]")
            op = "IS NOT NULL" if negate else "IS NULL"
            return _PropertyPredicate(var, prop, op, None)

        if tok.kind == "KW" and tok.value == "CONTAINS":
            self._advance()
            val_tok = self._expect("STRING")
            return _PropertyPredicate(var, prop, "CONTAINS", val_tok.value)

        if tok.kind == "OP":
            self._advance()
            val_tok = self._peek()
            if val_tok.kind == "STRING":
                self._advance()
                return _PropertyPredicate(var, prop, tok.value, val_tok.value)
            if val_tok.kind == "NUMBER":
                self._advance()
                num_val: Any = float(val_tok.value) if "." in val_tok.value else int(val_tok.value)
                return _PropertyPredicate(var, prop, tok.value, num_val)
            if val_tok.kind == "KW" and val_tok.value in ("TRUE", "FALSE"):
                self._advance()
                return _PropertyPredicate(var, prop, tok.value, val_tok.value == "TRUE")
            raise ValueError(
                f"Expected value after {tok.value!r} but got {val_tok.kind} at position {val_tok.pos}"
            )

        raise ValueError(
            f"Expected operator after {var}.{prop} but got {tok.kind}({tok.value!r}) "
            f"at position {tok.pos}"
        )


# ─── SQL compilation ───────────────────────────────────────────────────────


def _build_match_sql(pattern: _Pattern, where: Optional[_Predicate]) -> Tuple[str, List[Any]]:
    """Compile a parsed pattern + WHERE into a SQL query.

    Returns ``(sql, params)``. The SQL selects from graph_nodes joined via
    graph_edges according to the pattern, filtered by WHERE.

    For single-node patterns (no edges), the SQL is a simple SELECT on
    graph_nodes with label and WHERE filters.

    For multi-node patterns, each edge adds a JOIN on graph_edges.
    """
    nodes = pattern.nodes
    edges = pattern.edges
    n = len(nodes)

    # Build SELECT + FROM
    select_parts = []
    from_parts = []
    where_parts: List[str] = []
    params: List[Any] = []

    for idx, node in enumerate(nodes):
        alias = f"n{idx}"
        from_parts.append(f"graph_nodes AS {alias}")
        # Label filter
        if node.label:
            where_parts.append(f"{alias}.node_type = ?")
            params.append(node.label)

    # Edge joins
    for idx, edge in enumerate(edges):
        src_alias = f"n{idx}"
        tgt_alias = f"n{idx + 1}"
        e_alias = f"e{idx}"
        from_parts.append(f"graph_edges AS {e_alias}")
        where_parts.append(f"{e_alias}.edge_type = ?")
        params.append(edge.edge_type)

        if edge.direction == "right":
            where_parts.append(f"{e_alias}.source_id = {src_alias}.node_id")
            where_parts.append(f"{e_alias}.target_id = {tgt_alias}.node_id")
        elif edge.direction == "left":
            where_parts.append(f"{e_alias}.target_id = {src_alias}.node_id")
            where_parts.append(f"{e_alias}.source_id = {tgt_alias}.node_id")
        else:  # undirected
            where_parts.append(
                f"(({e_alias}.source_id = {src_alias}.node_id AND "
                f"{e_alias}.target_id = {tgt_alias}.node_id) OR "
                f"({e_alias}.source_id = {tgt_alias}.node_id AND "
                f"{e_alias}.target_id = {src_alias}.node_id))"
            )

    # WHERE predicate compilation
    if where is not None:
        pred_sql, pred_params = _compile_predicate(where, nodes)
        if pred_sql:
            where_parts.append(pred_sql)
            params.extend(pred_params)

    # SELECT all node columns for now (RETURN filtering happens post-query)
    for idx in range(n):
        alias = f"n{idx}"
        for col in ("id", "node_id", "node_type", "name", "file", "line"):
            select_parts.append(f"{alias}.{col} AS n{idx}_{col}")

    sql = "SELECT " + ", ".join(select_parts)
    sql += " FROM " + " JOIN ".join(from_parts)
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    return sql, params


def _compile_predicate(pred: _Predicate, nodes: List[_NodePattern]) -> Tuple[str, List[Any]]:
    """Compile a WHERE predicate to a SQL fragment + params."""
    if isinstance(pred, _BoolPredicate):
        left_sql, left_params = _compile_predicate(pred.left, nodes)
        right_sql, right_params = _compile_predicate(pred.right, nodes)
        if not left_sql or not right_sql:
            return "", []
        return f"({left_sql} {pred.op} {right_sql})", left_params + right_params

    if isinstance(pred, _PropertyPredicate):
        # Find which node alias this var refers to
        alias = _resolve_var(pred.var, nodes)
        if alias is None:
            raise ValueError(f"Unknown variable {pred.var!r} in WHERE clause")
        col = _NODE_PROPERTIES.get(pred.prop)
        if col is None:
            raise ValueError(
                f"Unknown property {pred.prop!r}. Valid: {sorted(_NODE_PROPERTIES)}"
            )
        full_col = f"{alias}.{col}"

        if pred.op == "IS NULL":
            return f"{full_col} IS NULL", []
        if pred.op == "IS NOT NULL":
            return f"{full_col} IS NOT NULL", []
        if pred.op == "CONTAINS":
            return f"{full_col} LIKE ?" , ["%" + str(pred.value) + "%"]
        if pred.op == "=":
            return f"{full_col} = ?", [pred.value]
        if pred.op == "!=":
            return f"{full_col} != ?", [pred.value]
        if pred.op == "<":
            return f"{full_col} < ?", [pred.value]
        if pred.op == ">":
            return f"{full_col} > ?", [pred.value]
        if pred.op == "<=":
            return f"{full_col} <= ?", [pred.value]
        if pred.op == ">=":
            return f"{full_col} >= ?", [pred.value]
        raise ValueError(f"Unsupported operator {pred.op!r}")

    if isinstance(pred, _NotExistsPredicate):
        # NOT EXISTS { pattern } — compile the inner pattern as a subquery
        # and negate it. This is used for dead-code detection:
        #   MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name
        #
        # The inner pattern references the outer query's node via a shared
        # variable. We need to correlate them.
        inner_sql, inner_params = _build_not_exists_subquery(pred.pattern, nodes)
        negate = not getattr(pred, "_exists_positive", False)
        if negate:
            return f"NOT EXISTS ({inner_sql})", inner_params
        return f"EXISTS ({inner_sql})", inner_params

    raise ValueError(f"Unknown predicate type {type(pred).__name__}")


def _build_not_exists_subquery(pattern: _Pattern, outer_nodes: List[_NodePattern]) -> Tuple[str, List[Any]]:
    """Build a correlated subquery for NOT EXISTS.

    The inner pattern's nodes may share variable names with the outer query.
    We correlate by matching shared variable names to their outer aliases.
    """
    inner_nodes = pattern.nodes
    inner_edges = pattern.edges

    # Map outer var names to their aliases (n0, n1, ...)
    outer_var_map: Dict[str, str] = {}
    for idx, node in enumerate(outer_nodes):
        if node.var:
            outer_var_map[node.var] = f"n{idx}"

    from_parts: List[str] = []
    where_parts: List[str] = []
    params: List[Any] = []

    for idx, node in enumerate(inner_nodes):
        alias = f"sub_n{idx}"
        from_parts.append(f"graph_nodes AS {alias}")
        if node.label:
            where_parts.append(f"{alias}.node_type = ?")
            params.append(node.label)
        # Correlate with outer query if var matches
        if node.var and node.var in outer_var_map:
            outer_alias = outer_var_map[node.var]
            where_parts.append(f"{alias}.node_id = {outer_alias}.node_id")

    for idx, edge in enumerate(inner_edges):
        src_alias = f"sub_n{idx}"
        tgt_alias = f"sub_n{idx + 1}"
        e_alias = f"sub_e{idx}"
        from_parts.append(f"graph_edges AS {e_alias}")
        where_parts.append(f"{e_alias}.edge_type = ?")
        params.append(edge.edge_type)

        if edge.direction == "right":
            where_parts.append(f"{e_alias}.source_id = {src_alias}.node_id")
            where_parts.append(f"{e_alias}.target_id = {tgt_alias}.node_id")
        elif edge.direction == "left":
            where_parts.append(f"{e_alias}.target_id = {src_alias}.node_id")
            where_parts.append(f"{e_alias}.source_id = {tgt_alias}.node_id")
        else:
            where_parts.append(
                f"(({e_alias}.source_id = {src_alias}.node_id AND "
                f"{e_alias}.target_id = {tgt_alias}.node_id) OR "
                f"({e_alias}.source_id = {tgt_alias}.node_id AND "
                f"{e_alias}.target_id = {src_alias}.node_id))"
            )

    # SELECT 1 is enough for EXISTS
    sql = "SELECT 1 FROM " + " JOIN ".join(from_parts)
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    return sql, params


def _resolve_var(var: str, nodes: List[_NodePattern]) -> Optional[str]:
    """Resolve a variable name to its node alias (n0, n1, ...)."""
    for idx, node in enumerate(nodes):
        if node.var == var:
            return f"n{idx}"
    return None


# ─── Result formatting ─────────────────────────────────────────────────────


def _row_to_result(row: sqlite3.Row, num_nodes: int) -> Dict[str, Any]:
    """Convert a SQL row to a result dict keyed by node variable."""
    result: Dict[str, Any] = {}
    for idx in range(num_nodes):
        node_data: Dict[str, Any] = {}
        for col in ("id", "node_id", "node_type", "name", "file", "line"):
            node_data[col] = row[f"n{idx}_{col}"]
        result[f"n{idx}"] = node_data
    return result


def _project_return(
    rows: List[Dict[str, Any]],
    return_items: List[Tuple[str, Optional[str]]],
    return_star: bool,
    nodes: List[_NodePattern],
) -> List[Dict[str, Any]]:
    """Project RETURN items from full rows.

    If return_star, return the full rows (all nodes).
    Otherwise, build a dict with the requested var.property pairs.
    """
    if return_star:
        # Rename n0/n1/... to the variable names where available
        renamed: List[Dict[str, Any]] = []
        for row in rows:
            out: Dict[str, Any] = {}
            for idx, node in enumerate(nodes):
                key = node.var or f"n{idx}"
                out[key] = row[f"n{idx}"]
            renamed.append(out)
        return renamed

    projected: List[Dict[str, Any]] = []
    var_to_idx: Dict[str, int] = {}
    for idx, node in enumerate(nodes):
        if node.var:
            var_to_idx[node.var] = idx

    for row in rows:
        out: Dict[str, Any] = {}
        for var, prop in return_items:
            if var not in var_to_idx:
                # Unknown var — skip with a placeholder so caller sees the issue
                out[var] = None
                continue
            idx = var_to_idx[var]
            node_data = row[f"n{idx}"]
            if prop is None:
                out[var] = node_data
            else:
                col = _NODE_PROPERTIES.get(prop, prop)
                out[f"{var}.{prop}"] = node_data.get(col)
        projected.append(out)
    return projected


# ─── Public API ────────────────────────────────────────────────────────────


def execute_query(
    query: str,
    workspace: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a Cypher-subset query against the code graph.

    Args:
        query:     The Cypher-subset query string (e.g.
                   ``MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file``).
        workspace: Absolute path to the workspace root.
        db_path:   Optional SQLite db path. Defaults to
                   ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys:
        - ``status``: ``"ok"`` or ``"error"``
        - ``query``: the original query string (for echo)
        - ``results``: list of result rows (projected per RETURN)
        - ``count``: number of result rows
        - ``truncated``: whether LIMIT was applied
        - ``error``: present only when status == "error"
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)

    # Parse
    try:
        tokens = _tokenize(query)
        parser = _Parser(tokens)
        ast = parser.parse()
    except ValueError as exc:
        return {
            "status": "error",
            "error": "parse_error",
            "message": str(exc),
            "query": query,
        }

    # Check DB exists
    if not os.path.exists(db_path):
        return {
            "status": "error",
            "error": "database_not_found",
            "message": f"Database not found at {db_path}. Run 'codelens scan' first.",
            "query": query,
        }

    # Build SQL
    try:
        sql, params = _build_match_sql(ast.pattern, ast.where)
    except ValueError as exc:
        return {
            "status": "error",
            "error": "compile_error",
            "message": str(exc),
            "query": query,
        }

    # Add LIMIT
    truncated = False
    if ast.limit is not None:
        sql += f" LIMIT {ast.limit}"
        truncated = True

    # Execute
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Check tables exist
            table_check = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('graph_nodes', 'graph_edges')"
            ).fetchall()
            table_names = {r[0] for r in table_check}
            if "graph_nodes" not in table_names or "graph_edges" not in table_names:
                return {
                    "status": "error",
                    "error": "graph_not_initialized",
                    "message": "Graph tables not found. Run 'codelens scan' first.",
                    "query": query,
                }

            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "error": "database_error",
            "message": str(exc),
            "query": query,
            "sql": sql,
        }

    # Format results
    num_nodes = len(ast.pattern.nodes)
    raw_results = [_row_to_result(r, num_nodes) for r in rows]
    projected = _project_return(raw_results, ast.return_items, ast.return_star, ast.pattern.nodes)

    return {
        "status": "ok",
        "query": query,
        "results": projected,
        "count": len(projected),
        "truncated": truncated,
        "limit": ast.limit,
    }


def validate_query(query: str) -> Dict[str, Any]:
    """Validate a query without executing it.

    Returns ``{"valid": True}`` or ``{"valid": False, "error": "..."}``.
    Useful for agents to check syntax before running against a large graph.
    """
    try:
        tokens = _tokenize(query)
        parser = _Parser(tokens)
        parser.parse()
        return {"valid": True}
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}

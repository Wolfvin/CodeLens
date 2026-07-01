"""
Cypher-subset query engine for the CodeLens graph model (issue #9).

Provides a read-only, openCypher-inspired query language over the
``graph_nodes`` + ``graph_edges`` SQLite tables populated during scan.
Agents can express structural questions in a single expressive query
instead of chaining ``trace`` + ``impact`` + ``context`` tool calls.

Supported subset (per issue #9 "minimal viable" scope):

    MATCH (f:Function)-[:CALLS]->(g)
    WHERE f.name = 'handleRequest'
    RETURN g.name, g.file

    MATCH (c:Class)-[:INHERITS]->(p)
    WHERE p.name = 'BaseModel'
    RETURN c.name

    MATCH (f:Function)
    WHERE NOT EXISTS { ()-[:CALLS]->(f) }
    RETURN f.name                     -- dead code (no callers)

Clauses:
    MATCH   — one or more comma-separated path patterns
    WHERE   — optional predicate (AND / OR / NOT / comparison / CONTAINS / IS NULL / EXISTS)
    RETURN  — variable.prop or variable (whole node)
    LIMIT   — optional row cap (default 100, hard cap 1000 to prevent runaway queries)

Predicates:
    n.prop = 'value'         (string equality)
    n.prop = 42              (integer equality)
    n.prop != 'value'        (inequality)
    n.prop CONTAINS 'value'  (substring match, case-sensitive)
    n.prop IS NULL           (property absent or column NULL)
    n.prop IS NOT NULL
    EXISTS { (m)-[:CALLS]->(n) }       (sub-pattern match)
    NOT EXISTS { ()-[:CALLS]->(n) }    (no incoming :CALLS edge)
    pred AND pred / pred OR pred / NOT pred

Node labels map to ``graph_nodes.node_type`` (case-insensitive):
    Function → function, Class → class, File → file, Module → module,
    Route → route, Type → type, Interface → interface

Edge types map to ``graph_edges.edge_type`` (case-insensitive):
    CALLS, IMPORTS, DEFINES, INHERITS, IMPLEMENTS, USES_TYPE

Security:
    All user-supplied literals are passed as SQL parameters — no string
    interpolation into SQL. Identifiers (variable names, property names,
    labels, edge types) are validated against an allow-list before
    inclusion in SQL to prevent injection via crafted identifiers.

This engine is **read-only** — no CREATE / SET / DELETE / MERGE clauses
are supported. A write clause in the query raises ``CypherParseError``.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from graph_model import (
    GRAPH_NODES_TABLE,
    GRAPH_EDGES_TABLE,
    NODE_TYPE_FUNCTION,
    NODE_TYPE_CLASS,
    NODE_TYPE_FILE,
    NODE_TYPE_MODULE,
    NODE_TYPE_ROUTE,
    NODE_TYPE_TYPE,
    NODE_TYPE_INTERFACE,
    graph_tables_exist,
)
from utils import default_db_path, logger

# ─── Constants ────────────────────────────────────────────────────────────

# Cypher labels → graph_nodes.node_type values. Case-insensitive lookup.
_LABEL_TO_NODE_TYPE: Dict[str, str] = {
    "function": NODE_TYPE_FUNCTION,
    "method": NODE_TYPE_FUNCTION,  # alias
    "component": NODE_TYPE_FUNCTION,  # React component is a function
    "class": NODE_TYPE_CLASS,
    "file": NODE_TYPE_FILE,
    "module": NODE_TYPE_MODULE,
    "route": NODE_TYPE_ROUTE,
    "type": NODE_TYPE_TYPE,
    "interface": NODE_TYPE_INTERFACE,
}

# Valid node properties (graph_nodes columns + extra_json keys).
_NODE_PROPERTIES = {"name", "file", "line", "node_type", "node_id"}

# Valid edge properties (graph_edges columns).
_EDGE_PROPERTIES = {"edge_type", "file", "line", "confidence"}

# Valid edge types — case-insensitive. User may write :CALLS or :calls.
_VALID_EDGE_TYPES = {
    "CALLS", "IMPORTS", "DEFINES", "INHERITS", "IMPLEMENTS", "USES_TYPE",
}

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


class CypherParseError(Exception):
    """Raised when the Cypher query cannot be parsed or violates the subset."""


class CypherExecutionError(Exception):
    """Raised when the translated SQL fails to execute."""


# ─── AST ──────────────────────────────────────────────────────────────────


@dataclass
class NodePattern:
    """A node pattern like ``(f:Function)`` or ``(g)`` or ``()``."""
    var: Optional[str] = None       # variable name, e.g. 'f'
    label: Optional[str] = None     # Cypher label, e.g. 'Function' (unmapped)

    def node_type(self) -> Optional[str]:
        """Map the Cypher label to a graph_nodes.node_type value."""
        if self.label is None:
            return None
        key = self.label.lower()
        if key not in _LABEL_TO_NODE_TYPE:
            raise CypherParseError(
                f"Unknown node label ': {self.label}'. Valid labels: "
                f"{sorted(set(_LABEL_TO_NODE_TYPE.keys()))}"
            )
        return _LABEL_TO_NODE_TYPE[key]


@dataclass
class EdgePattern:
    """An edge pattern like ``-[:CALLS]->``, ``<-[:IMPORTS]-``, or ``-[]-``."""
    edge_type: Optional[str] = None  # e.g. 'CALLS' (already upper-cased)
    direction: str = "->"            # '->', '<-', or '-' (undirected)
    target: NodePattern = field(default_factory=NodePattern)


@dataclass
class PathPattern:
    """A path pattern: start node + chain of edges."""
    start: NodePattern
    edges: List[EdgePattern] = field(default_factory=list)


# ─── Predicate AST ────────────────────────────────────────────────────────


@dataclass
class Comparison:
    """``var.prop OP value`` — e.g. ``f.name = 'handleRequest'``."""
    var: str
    prop: str
    op: str           # '=', '!=', '<', '>', '<=', '>=', 'CONTAINS'
    value: Any        # str or int — passed as SQL parameter


@dataclass
class IsNull:
    """``var.prop IS NULL`` or ``var.prop IS NOT NULL``."""
    var: str
    prop: str
    negate: bool = False


@dataclass
class ExistsSubquery:
    """``EXISTS { path_pattern }`` or ``NOT EXISTS { path_pattern }``.

    The inner path pattern is matched against the graph; the outer query
    row passes its bound node variables into the subquery so the pattern
    can reference them.
    """
    pattern: PathPattern
    negate: bool = False


@dataclass
class BoolOp:
    """``left AND right`` / ``left OR right``."""
    op: str            # 'AND' / 'OR'
    left: Any
    right: Any


@dataclass
class NotOp:
    """``NOT pred``."""
    pred: Any


@dataclass
class ReturnItem:
    """A single RETURN expression — either ``var.prop`` or bare ``var``."""
    var: str
    prop: Optional[str] = None   # None means return whole node as dict

    def display_name(self) -> str:
        if self.prop is None:
            return self.var
        return f"{self.var}.{self.prop}"


@dataclass
class CypherQuery:
    """Parsed Cypher query AST."""
    patterns: List[PathPattern] = field(default_factory=list)
    where: Optional[Any] = None
    return_items: List[ReturnItem] = field(default_factory=list)
    limit: Optional[int] = None


# ─── Tokenizer ────────────────────────────────────────────────────────────

# Token types.
_TOK_KEYWORD = "KEYWORD"
_TOK_IDENT = "IDENT"
_TOK_STRING = "STRING"
_TOK_NUMBER = "NUMBER"
_TOK_PUNCT = "PUNCT"
_TOK_EOF = "EOF"

_KEYWORDS = {
    "MATCH", "WHERE", "RETURN", "LIMIT", "AND", "OR", "NOT",
    "CONTAINS", "IS", "NULL", "EXISTS",
}

# Single-char punctuation that becomes its own token.
_SINGLE_PUNCT = set("()[]{}:,.<>=-")

# Multi-char operators.
_MULTI_OPS = ["<=", ">=", "!=", "<-", "->", "-[" ]


@dataclass
class Token:
    type: str
    value: str
    pos: int


def _tokenize(query: str) -> List[Token]:
    """Split a Cypher query string into tokens.

    Rules:
      - Whitespace separates tokens but is otherwise skipped.
      - ``--`` to end of line is a SQL-style comment (per issue example).
      - Single-quoted strings are string literals (no escape — Cypher uses
        ``''`` for embedded quotes, but we keep it simple and reject embedded
        quotes; agents can use double-quoted property values via parameterization
        at the API layer).
      - Identifiers start with a letter or underscore, continue with
        alphanumeric/underscore.
      - Numbers are non-negative integers (no floats needed for graph queries).
    """
    tokens: List[Token] = []
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]

        # Whitespace
        if ch.isspace():
            i += 1
            continue

        # Comment: -- to end of line
        if ch == "-" and i + 1 < n and query[i + 1] == "-":
            while i < n and query[i] != "\n":
                i += 1
            continue

        # String literal
        if ch == "'":
            j = i + 1
            buf: List[str] = []
            while j < n:
                if query[j] == "'":
                    if j + 1 < n and query[j + 1] == "'":
                        # Escaped quote
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(query[j])
                j += 1
            if j >= n:
                raise CypherParseError(
                    f"Unterminated string literal at position {i}: "
                    f"{query[i:i+20]!r}"
                )
            tokens.append(Token(_TOK_STRING, "".join(buf), i))
            i = j + 1
            continue

        # Number (non-negative integer)
        if ch.isdigit():
            j = i
            while j < n and query[j].isdigit():
                j += 1
            tokens.append(Token(_TOK_NUMBER, query[i:j], i))
            i = j
            continue

        # Identifier / keyword
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (query[j].isalnum() or query[j] == "_"):
                j += 1
            word = query[i:j]
            upper = word.upper()
            if upper in _KEYWORDS:
                tokens.append(Token(_TOK_KEYWORD, upper, i))
            else:
                tokens.append(Token(_TOK_IDENT, word, i))
            i = j
            continue

        # Multi-char operators (check before single-char)
        matched = False
        for op in _MULTI_OPS:
            if query[i:i + len(op)] == op:
                tokens.append(Token(_TOK_PUNCT, op, i))
                i += len(op)
                matched = True
                break
        if matched:
            continue

        # Single-char punctuation
        if ch in _SINGLE_PUNCT:
            # '-' is ambiguous: could be minus, or part of '->' / '<-' / '-['.
            # The multi-char pass above already caught '->', '<-', '-['.
            # A lone '-' is the edge dash.
            tokens.append(Token(_TOK_PUNCT, ch, i))
            i += 1
            continue

        raise CypherParseError(
            f"Unexpected character {ch!r} at position {i}: "
            f"{query[max(0, i-10):i+10]!r}"
        )

    tokens.append(Token(_TOK_EOF, "", n))
    return tokens


# ─── Parser (recursive descent) ───────────────────────────────────────────


class _Parser:
    """Recursive-descent parser for the Cypher subset.

    Grammar (simplified):

        query       := MATCH path (',' path)* [WHERE pred] RETURN ret (',' ret)* [LIMIT num]
        path        := node (edge node)*
        node        := '(' [var] [':' label] ')'
        edge        := '-' '[' [':' type] ']' '->'   |   '<-' '[' [':' type] ']' '-'   |   '-' '[' [':' type] ']' '-'
        pred        := or_pred
        or_pred     := and_pred (OR and_pred)*
        and_pred    := not_pred (AND not_pred)*
        not_pred    := NOT not_pred | atom
        atom        := '(' pred ')' | comparison | is_null | exists
        comparison  := var '.' prop op value
        is_null     := var '.' prop IS [NOT] NULL
        exists      := [NOT] EXISTS '{' path '}'
        ret         := var ['.' prop]
        op          := '=' | '!=' | '<' | '>' | '<=' | '>=' | CONTAINS
        value       := STRING | NUMBER
    """

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _next(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, ttype: str, value: Optional[str] = None) -> Token:
        tok = self._peek()
        if tok.type != ttype:
            raise CypherParseError(
                f"Expected {ttype} but got {tok.type} ({tok.value!r}) at pos {tok.pos}"
            )
        if value is not None and tok.value != value:
            raise CypherParseError(
                f"Expected {value!r} but got {tok.value!r} at pos {tok.pos}"
            )
        return self._next()

    def _accept(self, ttype: str, value: Optional[str] = None) -> Optional[Token]:
        tok = self._peek()
        if tok.type != ttype:
            return None
        if value is not None and tok.value != value:
            return None
        return self._next()

    def parse(self) -> CypherQuery:
        query = CypherQuery()

        # Reject write clauses up front — clearer error than falling through.
        # Write clause names are NOT in _KEYWORDS (they're treated as IDENT),
        # so we check by value (case-insensitive).
        _WRITE_CLAUSES = {"CREATE", "SET", "DELETE", "MERGE", "REMOVE", "DROP",
                          "INSERT", "UPDATE", "DETACH"}
        first = self._peek()
        if first.type == _TOK_IDENT and first.value.upper() in _WRITE_CLAUSES:
            raise CypherParseError(
                f"Write clause '{first.value}' is not supported — query_graph "
                f"is read-only (MATCH/WHERE/RETURN/LIMIT only)."
            )

        self._expect(_TOK_KEYWORD, "MATCH")

        # One or more comma-separated path patterns.
        query.patterns.append(self._parse_path())
        while self._accept(_TOK_PUNCT, ","):
            query.patterns.append(self._parse_path())

        # Check for write clauses after MATCH (e.g. "MATCH (n) DELETE n").
        next_tok = self._peek()
        if next_tok.type == _TOK_IDENT and next_tok.value.upper() in _WRITE_CLAUSES:
            raise CypherParseError(
                f"Write clause '{next_tok.value}' is not supported — query_graph "
                f"is read-only (MATCH/WHERE/RETURN/LIMIT only)."
            )

        # Optional WHERE.
        if self._accept(_TOK_KEYWORD, "WHERE"):
            query.where = self._parse_pred()

        # RETURN (required).
        self._expect(_TOK_KEYWORD, "RETURN")
        query.return_items.append(self._parse_return_item())
        while self._accept(_TOK_PUNCT, ","):
            query.return_items.append(self._parse_return_item())

        # Optional LIMIT.
        if self._accept(_TOK_KEYWORD, "LIMIT"):
            tok = self._expect(_TOK_NUMBER)
            query.limit = int(tok.value)
            if query.limit <= 0:
                raise CypherParseError(
                    f"LIMIT must be a positive integer, got {query.limit}"
                )
            if query.limit > MAX_LIMIT:
                raise CypherParseError(
                    f"LIMIT {query.limit} exceeds hard cap {MAX_LIMIT}. "
                    f"Use a smaller page size and paginate."
                )

        # Must be at EOF.
        if self._peek().type != _TOK_EOF:
            tok = self._peek()
            raise CypherParseError(
                f"Unexpected token after query end: {tok.value!r} at pos {tok.pos}"
            )

        # Validate that all variables in RETURN/WHERE are bound by MATCH.
        bound_vars: set = set()
        for pat in query.patterns:
            if pat.start.var:
                bound_vars.add(pat.start.var)
            for edge in pat.edges:
                if edge.target.var:
                    bound_vars.add(edge.target.var)

        for item in query.return_items:
            if item.var not in bound_vars:
                raise CypherParseError(
                    f"RETURN variable '{item.var}' is not bound by any MATCH "
                    f"pattern. Bound variables: {sorted(bound_vars)}"
                )

        if query.where is not None:
            self._validate_where_vars(query.where, bound_vars)

        return query

    def _validate_where_vars(self, pred: Any, bound_vars: set) -> None:
        """Recursively check that all variables in WHERE are bound."""
        if isinstance(pred, Comparison):
            if pred.var not in bound_vars:
                raise CypherParseError(
                    f"WHERE variable '{pred.var}' is not bound by any MATCH "
                    f"pattern. Bound variables: {sorted(bound_vars)}"
                )
        elif isinstance(pred, IsNull):
            if pred.var not in bound_vars:
                raise CypherParseError(
                    f"WHERE variable '{pred.var}' is not bound by any MATCH "
                    f"pattern. Bound variables: {sorted(bound_vars)}"
                )
        elif isinstance(pred, ExistsSubquery):
            # EXISTS sub-pattern may reference bound vars from outer query
            # (correlated subquery). Its own internal vars don't need to be
            # bound by the outer MATCH, but they must be self-consistent.
            inner_vars: set = set()
            if pred.pattern.start.var:
                inner_vars.add(pred.pattern.start.var)
            for edge in pred.pattern.edges:
                if edge.target.var:
                    inner_vars.add(edge.target.var)
            # No further validation — the translator will correlate.
        elif isinstance(pred, BoolOp):
            self._validate_where_vars(pred.left, bound_vars)
            self._validate_where_vars(pred.right, bound_vars)
        elif isinstance(pred, NotOp):
            self._validate_where_vars(pred.pred, bound_vars)

    def _parse_path(self) -> PathPattern:
        """Parse a path: node (edge node)*."""
        start = self._parse_node()
        path = PathPattern(start=start)

        while True:
            edge = self._try_parse_edge()
            if edge is None:
                break
            path.edges.append(edge)

        return path

    def _parse_node(self) -> NodePattern:
        """Parse ``(var:Label)`` or ``(var)`` or ``()``."""
        self._expect(_TOK_PUNCT, "(")
        node = NodePattern()

        # Optional variable.
        if self._peek().type == _TOK_IDENT:
            node.var = self._next().value

        # Optional label.
        if self._accept(_TOK_PUNCT, ":"):
            label_tok = self._expect(_TOK_IDENT)
            node.label = label_tok.value
            # Validate label at parse time so the error surfaces early
            # with a clear message (issue #9 test coverage).
            if node.label.lower() not in _LABEL_TO_NODE_TYPE:
                raise CypherParseError(
                    f"Unknown node label ': {node.label}'. Valid labels: "
                    f"{sorted(set(k for k in _LABEL_TO_NODE_TYPE if k.islower()))}"
                )

        self._expect(_TOK_PUNCT, ")")
        return node

    def _try_parse_edge(self) -> Optional[EdgePattern]:
        """Parse an edge pattern. Returns None if the next token isn't an edge start.

        Edge forms:
            -[:TYPE]->       (right-directed)
            <-[:TYPE]-       (left-directed)
            -[:TYPE]-        (undirected)
            -[]->            (no type)
        """
        # An edge starts with either '<-' or '-'.
        tok = self._peek()
        if tok.type != _TOK_PUNCT:
            return None
        if tok.value == "<-":
            self._next()
            direction = "<-"
        elif tok.value == "-":
            # Could be '-' followed by '[' (edge bracket), or '-' followed
            # by '>' (malformed '->' without brackets — reject).
            self._next()
            direction = "-"  # tentative; will refine after brackets
        elif tok.value == "-[":
            # Multi-char token from the multi-op pass.
            self._next()
            # We consumed '-[' — parse the rest as edge body.
            return self._parse_edge_body(direction="-", already_consumed_bracket=True)
        else:
            return None

        # After consuming '<-' or '-', we may have '[' for the edge body.
        if direction == "<-":
            # Expect '['
            if self._accept(_TOK_PUNCT, "["):
                return self._parse_edge_body(direction="<-", already_consumed_bracket=False)
            # '<-' without brackets — treat as undirected edge with no type.
            # But '<-' alone doesn't have a target. This is malformed.
            raise CypherParseError(
                f"Expected '[' after '<-' at pos {self._peek().pos}"
            )
        else:
            # direction == '-', we may have '[' next.
            if self._accept(_TOK_PUNCT, "["):
                return self._parse_edge_body(direction="-", already_consumed_bracket=False)
            # '-' without '[' — malformed edge (need brackets for edge type).
            # But wait — could be the start of '->'. Check.
            if self._accept(_TOK_PUNCT, ">"):
                # '->' without brackets — undirected-ish but actually means
                # right-directed edge with no type. Accept it.
                target = self._parse_node()
                return EdgePattern(edge_type=None, direction="->", target=target)
            raise CypherParseError(
                f"Expected '[' or '>' after '-' at pos {self._peek().pos}"
            )

    def _parse_edge_body(self, direction: str, already_consumed_bracket: bool) -> EdgePattern:
        """Parse the ``:TYPE]`` part of an edge (bracket already open)."""
        edge_type: Optional[str] = None

        if self._accept(_TOK_PUNCT, ":"):
            type_tok = self._expect(_TOK_IDENT)
            raw_type = type_tok.value.upper()
            if raw_type not in _VALID_EDGE_TYPES:
                raise CypherParseError(
                    f"Unknown edge type ': {type_tok.value}'. Valid types: "
                    f"{sorted(_VALID_EDGE_TYPES)}"
                )
            edge_type = raw_type

        # Close bracket.
        self._expect(_TOK_PUNCT, "]")

        # After ']', expect the direction arrow.
        if direction == "<-":
            # '<-[:TYPE]-' — expect '-' to close.
            self._expect(_TOK_PUNCT, "-")
            final_direction = "<-"
        elif direction == "-":
            # '-[:TYPE]->' or '-[:TYPE]-'
            # Note: '->' is tokenized as a single PUNCT token (multi-char op).
            if self._accept(_TOK_PUNCT, "->"):
                final_direction = "->"
            elif self._accept(_TOK_PUNCT, "-"):
                final_direction = "-"
            else:
                raise CypherParseError(
                    f"Expected '->' or '-' after edge type at pos {self._peek().pos}"
                )
        else:
            raise CypherParseError(f"Internal parser error: bad direction {direction!r}")

        target = self._parse_node()
        return EdgePattern(edge_type=edge_type, direction=final_direction, target=target)

    # ─── Predicate parsing ─────────────────────────────────────────────

    def _parse_pred(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._accept(_TOK_KEYWORD, "OR"):
            right = self._parse_and()
            left = BoolOp(op="OR", left=left, right=right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        while self._accept(_TOK_KEYWORD, "AND"):
            right = self._parse_not()
            left = BoolOp(op="AND", left=left, right=right)
        return left

    def _parse_not(self) -> Any:
        if self._accept(_TOK_KEYWORD, "NOT"):
            # NOT can precede EXISTS or a parenthesized predicate or a comparison.
            if self._peek().type == _TOK_KEYWORD and self._peek().value == "EXISTS":
                self._next()
                return self._parse_exists_body(negate=True)
            return NotOp(pred=self._parse_not())
        return self._parse_atom()

    def _parse_atom(self) -> Any:
        tok = self._peek()

        # Parenthesized predicate.
        if tok.type == _TOK_PUNCT and tok.value == "(":
            # But wait — '(' could also start a node pattern inside EXISTS.
            # We only reach here for top-level predicates, so '(' means
            # a parenthesized boolean expression.
            self._next()
            inner = self._parse_pred()
            self._expect(_TOK_PUNCT, ")")
            return inner

        # EXISTS { path }
        if tok.type == _TOK_KEYWORD and tok.value == "EXISTS":
            self._next()
            return self._parse_exists_body(negate=False)

        # var.prop ...
        if tok.type == _TOK_IDENT:
            return self._parse_comparison_or_isnull()

        raise CypherParseError(
            f"Expected predicate at pos {tok.pos}, got {tok.value!r}"
        )

    def _parse_exists_body(self, negate: bool) -> ExistsSubquery:
        """Parse ``{ path }`` after EXISTS keyword."""
        self._expect(_TOK_PUNCT, "{")
        path = self._parse_path()
        self._expect(_TOK_PUNCT, "}")
        return ExistsSubquery(pattern=path, negate=negate)

    def _parse_comparison_or_isnull(self) -> Any:
        """Parse ``var.prop OP value`` or ``var.prop IS [NOT] NULL``."""
        var_tok = self._expect(_TOK_IDENT)
        self._expect(_TOK_PUNCT, ".")
        prop_tok = self._expect(_TOK_IDENT)
        var = var_tok.value
        prop = prop_tok.value

        # Validate property name against allow-list.
        if prop not in _NODE_PROPERTIES and prop not in _EDGE_PROPERTIES:
            raise CypherParseError(
                f"Unknown property '{prop}'. Valid node properties: "
                f"{sorted(_NODE_PROPERTIES)}, edge properties: {sorted(_EDGE_PROPERTIES)}"
            )

        # IS NULL / IS NOT NULL
        if self._accept(_TOK_KEYWORD, "IS"):
            negate = bool(self._accept(_TOK_KEYWORD, "NOT"))
            self._expect(_TOK_KEYWORD, "NULL")
            return IsNull(var=var, prop=prop, negate=negate)

        # Comparison operator.
        op_tok = self._peek()
        if op_tok.type == _TOK_KEYWORD and op_tok.value == "CONTAINS":
            self._next()
            op = "CONTAINS"
        elif op_tok.type == _TOK_PUNCT and op_tok.value in ("=", "!=", "<", ">", "<=", ">="):
            op = self._next().value
        else:
            raise CypherParseError(
                f"Expected comparison operator (=, !=, <, >, <=, >=, CONTAINS) "
                f"or IS [NOT] NULL at pos {op_tok.pos}, got {op_tok.value!r}"
            )

        # Value.
        val_tok = self._peek()
        if val_tok.type == _TOK_STRING:
            value: Any = self._next().value
        elif val_tok.type == _TOK_NUMBER:
            value = int(self._next().value)
        else:
            raise CypherParseError(
                f"Expected string or number value at pos {val_tok.pos}, "
                f"got {val_tok.value!r}"
            )

        return Comparison(var=var, prop=prop, op=op, value=value)

    def _parse_return_item(self) -> ReturnItem:
        """Parse ``var`` or ``var.prop``."""
        var_tok = self._expect(_TOK_IDENT)
        item = ReturnItem(var=var_tok.value)

        if self._accept(_TOK_PUNCT, "."):
            prop_tok = self._expect(_TOK_IDENT)
            item.prop = prop_tok.value
            # Validate property.
            if item.prop not in _NODE_PROPERTIES and item.prop not in _EDGE_PROPERTIES:
                raise CypherParseError(
                    f"Unknown property '{item.prop}' in RETURN. Valid: "
                    f"{sorted(_NODE_PROPERTIES | _EDGE_PROPERTIES)}"
                )

        return item


def parse(query: str) -> CypherQuery:
    """Parse a Cypher query string into a validated AST.

    Raises:
        CypherParseError: if the query violates the supported subset or
            references unknown labels / edge types / properties.
    """
    tokens = _tokenize(query)
    parser = _Parser(tokens)
    return parser.parse()


# ─── SQL Translator ───────────────────────────────────────────────────────


def _table_alias_for_var(var: str, counter: Dict[str, int]) -> str:
    """Generate a stable SQL table alias for a node variable.

    Uses ``n_<var>`` to avoid collisions with SQL keywords. If the same
    variable appears in multiple patterns (unlikely but possible with
    correlated EXISTS), the counter disambiguates.
    """
    # Sanitize: only alnum + underscore allowed in var (enforced by tokenizer).
    return f"n_{var}"


def _translate_pattern(
    pattern: PathPattern,
    alias_map: Dict[str, str],
    params: list,
    alias_counter: List[int],
) -> Tuple[str, str]:
    """Translate a path pattern to a FROM + WHERE SQL fragment.

    Returns ``(from_clause, where_clause)`` where ``from_clause`` is the
    list of table joins and ``where_clause`` is the conjunction of node
    type + edge type constraints.

    ``alias_map`` is updated in place: var → SQL alias.
    """
    from_parts: List[str] = []
    where_parts: List[str] = []

    # Start node.
    start = pattern.start
    if start.var is None:
        # Anonymous start node — generate a throwaway alias.
        alias_counter[0] += 1
        start_alias = f"n_anon{alias_counter[0]}"
    else:
        start_alias = _table_alias_for_var(start.var, {})
        if start.var in alias_map:
            # Variable already bound — reuse the existing alias.
            start_alias = alias_map[start.var]
        else:
            alias_map[start.var] = start_alias

    from_parts.append(f"{GRAPH_NODES_TABLE} AS {start_alias}")

    # Node type constraint on start.
    node_type = start.node_type()
    if node_type is not None:
        where_parts.append(f"{start_alias}.node_type = ?")
        params.append(node_type)

    # Walk the edge chain.
    prev_alias = start_alias
    for idx, edge in enumerate(pattern.edges):
        alias_counter[0] += 1
        edge_alias = f"e_{alias_counter[0]}"
        alias_counter[0] += 1

        # Target node.
        target = edge.target
        target_is_new = target.var is None or target.var not in alias_map
        if target.var is None:
            target_alias = f"n_anon{alias_counter[0]}"
        else:
            if target.var in alias_map:
                target_alias = alias_map[target.var]
            else:
                target_alias = _table_alias_for_var(target.var, {})
                alias_map[target.var] = target_alias

        # Build edge JOIN clause (depends on direction).
        # When target is already bound (correlated subquery), we DON'T join
        # the target node table — instead we add a WHERE condition correlating
        # the edge's source/target_id to the existing alias.
        if edge.direction == "->":
            edge_join = (
                f"JOIN {GRAPH_EDGES_TABLE} AS {edge_alias} "
                f"ON {edge_alias}.source_id = {prev_alias}.node_id"
            )
            if target_is_new:
                target_join = (
                    f"JOIN {GRAPH_NODES_TABLE} AS {target_alias} "
                    f"ON {target_alias}.node_id = {edge_alias}.target_id"
                )
            else:
                # Correlated: edge.target_id must equal the existing target alias.
                target_join = None
                where_parts.append(
                    f"{edge_alias}.target_id = {target_alias}.node_id"
                )
        elif edge.direction == "<-":
            edge_join = (
                f"JOIN {GRAPH_EDGES_TABLE} AS {edge_alias} "
                f"ON {edge_alias}.target_id = {prev_alias}.node_id"
            )
            if target_is_new:
                target_join = (
                    f"JOIN {GRAPH_NODES_TABLE} AS {target_alias} "
                    f"ON {target_alias}.node_id = {edge_alias}.source_id"
                )
            else:
                # Correlated: edge.source_id must equal the existing target alias.
                target_join = None
                where_parts.append(
                    f"{edge_alias}.source_id = {target_alias}.node_id"
                )
        else:  # "-"
            # Undirected — match either direction. Use OR.
            edge_join = (
                f"JOIN {GRAPH_EDGES_TABLE} AS {edge_alias} "
                f"ON ({edge_alias}.source_id = {prev_alias}.node_id "
                f"OR {edge_alias}.target_id = {prev_alias}.node_id)"
            )
            if target_is_new:
                target_join = (
                    f"JOIN {GRAPH_NODES_TABLE} AS {target_alias} "
                    f"ON ({target_alias}.node_id = {edge_alias}.target_id "
                    f"OR {target_alias}.node_id = {edge_alias}.source_id) "
                    f"AND {target_alias}.node_id != {prev_alias}.node_id"
                )
            else:
                # Correlated undirected — either direction matches the target.
                target_join = None
                where_parts.append(
                    f"({edge_alias}.target_id = {target_alias}.node_id "
                    f"OR {edge_alias}.source_id = {target_alias}.node_id) "
                    f"AND {target_alias}.node_id != {prev_alias}.node_id"
                )

        from_parts.append(edge_join)
        if target_join is not None:
            from_parts.append(target_join)

        # Edge type constraint.
        if edge.edge_type is not None:
            where_parts.append(f"{edge_alias}.edge_type = ?")
            params.append(edge.edge_type)

        # Target node type constraint.
        target_type = target.node_type()
        if target_type is not None:
            where_parts.append(f"{target_alias}.node_type = ?")
            params.append(target_type)

        prev_alias = target_alias

    from_clause = " ".join(from_parts)
    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    return from_clause, where_clause


def _translate_predicate(
    pred: Any,
    alias_map: Dict[str, str],
    params: list,
    alias_counter: List[int],
) -> str:
    """Translate a predicate AST node to a SQL WHERE fragment."""
    if isinstance(pred, Comparison):
        alias = alias_map.get(pred.var)
        if alias is None:
            # Could be a var referenced only in EXISTS — but we validated
            # at parse time that WHERE vars are bound. This is a bug.
            raise CypherExecutionError(
                f"Variable '{pred.var}' not bound to a SQL alias. This is a bug."
            )
        col = f"{alias}.{pred.prop}"
        if pred.op == "CONTAINS":
            # LIKE with %wildcards% on both sides for substring match.
            params.append(f"%{pred.value}%")
            return f"{col} LIKE ?"
        else:
            params.append(pred.value)
            op_map = {"=": "=", "!=": "!=", "<": "<", ">": ">",
                      "<=": "<=", ">=": ">="}
            return f"{col} {op_map[pred.op]} ?"

    if isinstance(pred, IsNull):
        alias = alias_map.get(pred.var)
        if alias is None:
            raise CypherExecutionError(
                f"Variable '{pred.var}' not bound to a SQL alias. This is a bug."
            )
        col = f"{alias}.{pred.prop}"
        if pred.negate:
            return f"{col} IS NOT NULL"
        return f"{col} IS NULL"

    if isinstance(pred, ExistsSubquery):
        # Translate the inner path to a correlated EXISTS subquery.
        inner_alias_map: Dict[str, str] = dict(alias_map)  # inherit outer bindings
        inner_from, inner_where = _translate_pattern(
            pred.pattern, inner_alias_map, params, alias_counter
        )
        sql = f"EXISTS (SELECT 1 FROM {inner_from} WHERE {inner_where})"
        if pred.negate:
            sql = f"NOT {sql}"
        return sql

    if isinstance(pred, BoolOp):
        left_sql = _translate_predicate(pred.left, alias_map, params, alias_counter)
        right_sql = _translate_predicate(pred.right, alias_map, params, alias_counter)
        return f"({left_sql} {pred.op} {right_sql})"

    if isinstance(pred, NotOp):
        inner_sql = _translate_predicate(pred.pred, alias_map, params, alias_counter)
        return f"(NOT {inner_sql})"

    raise CypherExecutionError(f"Unknown predicate type {type(pred).__name__}")


def _translate_return(
    return_items: List[ReturnItem],
    alias_map: Dict[str, str],
) -> Tuple[str, List[str]]:
    """Translate RETURN items to a SELECT column list + display names.

    For ``var.prop`` → ``alias.prop``.
    For ``var`` (whole node) → ``alias.node_id, alias.node_type, alias.name,
    alias.file, alias.line`` — returned as a dict in the row processor.
    """
    cols: List[str] = []
    display_names: List[str] = []
    for item in return_items:
        alias = alias_map.get(item.var)
        if alias is None:
            raise CypherExecutionError(
                f"RETURN variable '{item.var}' not bound to a SQL alias. This is a bug."
            )
        if item.prop is None:
            # Whole node — select all columns.
            cols.extend([
                f"{alias}.node_id",
                f"{alias}.node_type",
                f"{alias}.name",
                f"{alias}.file",
                f"{alias}.line",
            ])
            display_names.append(item.var)
        else:
            cols.append(f"{alias}.{item.prop}")
            display_names.append(item.display_name())

    select_clause = ", ".join(cols)
    return select_clause, display_names


def translate(query: CypherQuery) -> Tuple[str, list, List[ReturnItem]]:
    """Translate a parsed Cypher query to a parameterized SQL statement.

    Returns ``(sql, params, return_items)``.

    The SQL uses ``?`` placeholders for all user-supplied literals
    (string/number values in WHERE). Identifiers (variable names, property
    names, labels, edge types) are validated against allow-lists at parse
    time and are safe to interpolate into SQL.

    Args:
        query: Parsed Cypher query AST from :func:`parse`.

    Returns:
        Tuple of (SQL string, parameter list, return items for row processing).
    """
    alias_map: Dict[str, str] = {}
    params: list = []
    alias_counter: List[int] = [0]

    # Translate all MATCH patterns into FROM + WHERE fragments.
    from_clauses: List[str] = []
    where_parts: List[str] = []
    for pat in query.patterns:
        from_clause, pat_where = _translate_pattern(pat, alias_map, params, alias_counter)
        from_clauses.append(from_clause)
        if pat_where and pat_where != "1=1":
            where_parts.append(pat_where)

    # Translate WHERE predicate (if any).
    if query.where is not None:
        pred_sql = _translate_predicate(query.where, alias_map, params, alias_counter)
        where_parts.append(pred_sql)

    # Translate RETURN.
    select_clause, _ = _translate_return(query.return_items, alias_map)

    # Combine FROM — multiple comma-separated patterns become CROSS JOIN
    # (rare in practice; most queries have a single pattern).
    from_sql = ", ".join(from_clauses) if len(from_clauses) > 1 else from_clauses[0]

    # Combine WHERE.
    where_sql = " AND ".join(where_parts) if where_parts else "1=1"

    # LIMIT.
    limit = query.limit if query.limit is not None else DEFAULT_LIMIT
    # Append limit as a param so it's type-safe.
    params.append(limit)

    sql = f"SELECT {select_clause} FROM {from_sql} WHERE {where_sql} LIMIT ?"
    return sql, params, query.return_items


# ─── Executor ─────────────────────────────────────────────────────────────


def _row_to_result(
    row: sqlite3.Row,
    return_items: List[ReturnItem],
) -> Dict[str, Any]:
    """Convert a SQL row to a result dict keyed by RETURN display names.

    For ``var.prop`` returns → ``{"var.prop": value}``.
    For ``var`` (whole node) returns → ``{"var": {node_id, node_type, name, file, line}}``.
    """
    result: Dict[str, Any] = {}
    col_idx = 0
    for item in return_items:
        if item.prop is None:
            # Whole node — 5 columns.
            result[item.var] = {
                "node_id": row[col_idx],
                "node_type": row[col_idx + 1],
                "name": row[col_idx + 2],
                "file": row[col_idx + 3],
                "line": row[col_idx + 4],
            }
            col_idx += 5
        else:
            result[item.display_name()] = row[col_idx]
            col_idx += 1
    return result


def execute(
    query: CypherQuery,
    db_path: str,
) -> Dict[str, Any]:
    """Execute a parsed Cypher query against the graph SQLite database.

    Args:
        query: Parsed Cypher query AST.
        db_path: Path to the SQLite database (``<workspace>/.codelens/codelens.db``).

    Returns:
        Dict with keys:
            - ``status``: "ok" or "error"
            - ``rows``: list of result dicts (one per matching row)
            - ``row_count``: number of rows returned
            - ``truncated``: True if LIMIT was hit (heuristic: row_count == limit)
            - ``query``: original query string (for debugging)
            - ``sql``: translated SQL (for debugging / EXPLAIN)
            - ``elapsed_ms``: execution time in milliseconds
            - ``error``: error message (only when status == "error")
    """
    import time

    if not os.path.exists(db_path):
        return {
            "status": "error",
            "error": f"Database not found at {db_path}. Run 'codelens scan' first.",
            "rows": [],
            "row_count": 0,
        }

    if not graph_tables_exist(db_path):
        return {
            "status": "error",
            "error": "Graph tables not initialized. Run 'codelens scan' first.",
            "rows": [],
            "row_count": 0,
        }

    try:
        sql, params, return_items = translate(query)
    except (CypherParseError, CypherExecutionError) as e:
        return {
            "status": "error",
            "error": str(e),
            "rows": [],
            "row_count": 0,
        }

    start = time.time()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"SQL execution failed: {e}",
            "sql": sql,
            "params": params,
            "rows": [],
            "row_count": 0,
            "elapsed_ms": int((time.time() - start) * 1000),
        }

    elapsed_ms = int((time.time() - start) * 1000)
    result_rows = [_row_to_result(r, return_items) for r in rows]
    limit = query.limit if query.limit is not None else DEFAULT_LIMIT

    return {
        "status": "ok",
        "rows": result_rows,
        "row_count": len(result_rows),
        "truncated": len(result_rows) == limit,
        "sql": sql,
        "elapsed_ms": elapsed_ms,
    }


def query_graph(
    cypher: str,
    workspace: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """High-level entry point: parse + execute a Cypher query.

    Args:
        cypher: Cypher query string.
        workspace: Workspace root path (for default db_path resolution).
        db_path: Optional explicit db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Result dict from :func:`execute`, plus the original query string
        and (on parse error) a ``parse_error`` field.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)

    try:
        parsed = parse(cypher)
    except CypherParseError as e:
        return {
            "status": "error",
            "error": f"Parse error: {e}",
            "parse_error": str(e),
            "query": cypher,
            "rows": [],
            "row_count": 0,
        }

    result = execute(parsed, db_path)
    result["query"] = cypher
    return result

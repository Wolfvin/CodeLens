"""
CodeLens — Minimal openCypher-subset parser + evaluator.

Implements the MVP scope from issue #9:
  - MATCH clause with node + relationship patterns
  - WHERE clause with basic predicates (=, !=, CONTAINS, IS NULL, IS NOT NULL, NOT EXISTS)
  - RETURN clause with property projection + LIMIT
  - Read-only (no CREATE/UPDATE/DELETE)

Supported query shapes
----------------------
    MATCH (n) RETURN n.name, n.file LIMIT 10
    MATCH (f:Function) RETURN f.name, f.file
    MATCH (f:Function)-[:CALLS]->(g) RETURN f.name, g.name
    MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.name = 'handleRequest' RETURN g.name, g.file
    MATCH (c:Class)-[:INHERITS]->(p) WHERE p.name = 'BaseModel' RETURN c.name
    MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) } RETURN f.name

Unsupported (deliberately out of MVP scope)
-------------------------------------------
  - WITH, ORDER BY, SKIP, DISTINCT, aggregation (COUNT, SUM, etc.)
  - Multiple MATCH clauses chained
  - Variable-length paths ([:CALLS*])
  - Optional matches (OPTIONAL MATCH)
  - String regex matching (only = and CONTAINS)
  - Write clauses (CREATE, MERGE, DELETE, SET)

These can be added in follow-up PRs once the MVP is proven.

Architecture
------------
  1. Tokenizer (``tokenize``) — splits the query string into a flat
     list of tokens (parens, colons, identifiers, strings, arrows,
     operators).
  2. Parser (``parse_query``) — builds a ``Query`` AST from the
     token stream.
  3. Evaluator (``evaluate``) — runs the parsed ``Query`` against
     the CodeLens SQLite graph tables and returns rows.

The evaluator is intentionally separate from the parser so the parser
can be unit-tested without a database.

File header — CodeLens Cypher-subset parser (issue #9 MVP).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# AST types
# ---------------------------------------------------------------------------

@dataclass
class NodePattern:
    """A node pattern like ``(f:Function)`` or ``(n)``.

    Attributes:
        variable: the binding name (e.g. ``f``, ``n``). May be empty
            for anonymous nodes (e.g. ``()`` in ``NOT EXISTS { ()-[:CALLS]->(f) }``).
        labels: list of node labels (e.g. ``["Function"]``). May be
            empty — matches any node type.
    """
    variable: str = ""
    labels: List[str] = field(default_factory=list)


@dataclass
class RelationshipPattern:
    """A relationship pattern like ``-[:CALLS]->`` or ``<-[:IMPORTS]-``.

    Attributes:
        edge_type: the edge type filter (e.g. ``CALLS``). May be empty
            — matches any edge type.
        direction: ``"right"`` (``->``), ``"left"`` (``<-``), or
            ``"both"`` (``-``).
        variable: the binding name for the edge itself (rarely used
            in MVP — most queries don't bind edges).
    """
    edge_type: str = ""
    direction: str = "right"  # "right", "left", "both"
    variable: str = ""


@dataclass
class PathPattern:
    """A path pattern: alternating node + relationship patterns.

    Always starts and ends with a NodePattern. The relationships list
    has length = len(nodes) - 1.
    """
    nodes: List[NodePattern] = field(default_factory=list)
    relationships: List[RelationshipPattern] = field(default_factory=list)


@dataclass
class Comparison:
    """A WHERE predicate like ``f.name = 'handleRequest'``."""
    variable: str
    property: str
    operator: str  # "=", "!=", "CONTAINS", "IS NULL", "IS NOT NULL"
    value: Any  # string for = / != / CONTAINS; None for IS NULL


@dataclass
class NotExistsPattern:
    """A ``NOT EXISTS { <path> }`` predicate — true when no path matches."""
    path: PathPattern


@dataclass
class ReturnItem:
    """A single RETURN column like ``f.name`` or ``g``."""
    variable: str
    property: str = ""  # empty = return the whole node dict


@dataclass
class Query:
    """Parsed Cypher query AST."""
    match: List[PathPattern] = field(default_factory=list)
    where: List[Union[Comparison, NotExistsPattern]] = field(default_factory=list)
    return_items: List[ReturnItem] = field(default_factory=list)
    limit: Optional[int] = None


class CypherParseError(ValueError):
    """Raised when the query cannot be parsed."""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Token types: (regex, kind). Order matters — longer matches first.
# Note: we deliberately keep the token spec minimal — no compound
# tokens like ``->`` or ``[:``. The parser composes these from the
# basic tokens (``DASH`` + ``GT``, ``LBRACKET`` + ``COLON``, etc.).
# This keeps the tokenizer trivial and the parser the single source
# of truth for syntactic structure.
_TOKEN_SPEC: List[Tuple[str, str]] = [
    (r"\s+",                              "WS"),
    (r"//[^\n]*",                         "COMMENT"),
    (r"\"(?:[^\"\\]|\\.)*\"",             "STRING"),
    (r"'(?:[^'\\]|\\.)*'",                "STRING"),
    (r"\[",                               "LBRACKET"),
    (r"\]",                               "RBRACKET"),
    (r"\(",                               "LPAREN"),
    (r"\)",                               "RPAREN"),
    (r"\{",                               "LBRACE"),
    (r"\}",                               "RBRACE"),
    (r":",                                "COLON"),
    (r",",                                "COMMA"),
    (r"\.",                               "DOT"),
    (r"=",                                "EQ"),
    (r"!=",                               "NEQ"),
    (r"-",                                "DASH"),
    (r">",                                "GT"),
    (r"<",                                "LT"),
    (r"\d+",                              "NUMBER"),
    (r"[A-Za-z_][A-Za-z0-9_]*",           "IDENT"),
]


def tokenize(query: str) -> List[Tuple[str, str]]:
    """Split a Cypher query string into tokens.

    Returns a list of ``(kind, text)`` tuples. Whitespace and comments
    are dropped. Raises ``CypherParseError`` if the input contains a
    character that does not match any token spec.
    """
    tokens: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(query):
        for pattern, kind in _TOKEN_SPEC:
            m = re.match(pattern, query[pos:], re.DOTALL)
            if m:
                text = m.group(0)
                pos += len(text)
                if kind in ("WS", "COMMENT"):
                    break
                tokens.append((kind, text))
                break
        else:
            raise CypherParseError(
                f"unexpected character {query[pos]!r} at position {pos}"
            )
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive-descent parser over the token list."""

    def __init__(self, tokens: List[Tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> Optional[Tuple[str, str]]:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return None
        return self.tokens[idx]

    def advance(self) -> Tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str, text: Optional[str] = None) -> Tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise CypherParseError(f"expected {kind} but reached end of input")
        if tok[0] != kind or (text is not None and tok[1].upper() != text.upper()):
            raise CypherParseError(
                f"expected {kind}" + (f" '{text}'" if text else "")
                + f" but got {tok[0]} '{tok[1]}'"
            )
        return self.advance()

    def match_keyword(self, keyword: str) -> bool:
        """Check if the next token is the given keyword (case-insensitive)."""
        tok = self.peek()
        if tok is None:
            return False
        if tok[0] == "IDENT" and tok[1].upper() == keyword.upper():
            self.advance()
            return True
        return False

    def is_keyword(self, keyword: str) -> bool:
        """Peek-only check — does not advance."""
        tok = self.peek()
        if tok is None:
            return False
        return tok[0] == "IDENT" and tok[1].upper() == keyword.upper()

    def parse_query(self) -> Query:
        q = Query()
        # Mandatory: MATCH
        if not self.match_keyword("MATCH"):
            raise CypherParseError(
                "query must start with MATCH (only MATCH is supported in MVP)"
            )
        q.match.append(self.parse_path_pattern())

        # Optional: WHERE
        if self.match_keyword("WHERE"):
            q.where = self.parse_where_clauses()

        # Mandatory: RETURN
        if not self.match_keyword("RETURN"):
            raise CypherParseError("query must have a RETURN clause")
        q.return_items = self.parse_return_items()

        # Optional: LIMIT
        if self.match_keyword("LIMIT"):
            tok = self.expect("NUMBER")
            q.limit = int(tok[1])

        # Optional trailing semicolon or end-of-input
        if self.peek() is not None:
            tok = self.peek()
            raise CypherParseError(
                f"unexpected trailing token {tok[0]} '{tok[1]}' — "
                f"MVP only supports one MATCH + WHERE + RETURN + LIMIT"
            )

        return q

    def parse_path_pattern(self) -> PathPattern:
        """Parse a path like ``(f:Function)-[:CALLS]->(g)``."""
        path = PathPattern()
        path.nodes.append(self.parse_node_pattern())
        while True:
            # Look ahead: is the next token a relationship start?
            tok = self.peek()
            if tok is None:
                break
            # A relationship starts with ``-``, ``<-``, or ``-[:`` (DASH, LT, or DASH+COLON)
            # We handle the three cases in parse_relationship_pattern.
            if tok[0] in ("DASH", "LT"):
                rel = self.parse_relationship_pattern()
                node = self.parse_node_pattern()
                path.relationships.append(rel)
                path.nodes.append(node)
            else:
                break
        return path

    def parse_node_pattern(self) -> NodePattern:
        """Parse ``(f:Function)`` or ``(n)`` or ``()``."""
        self.expect("LPAREN")
        node = NodePattern()
        tok = self.peek()
        if tok and tok[0] == "IDENT":
            node.variable = self.advance()[1]
        # Optional label(s): :Function:Class
        while True:
            tok = self.peek()
            if tok and tok[0] == "COLON":
                self.advance()
                label_tok = self.expect("IDENT")
                node.labels.append(label_tok[1])
            else:
                break
        self.expect("RPAREN")
        return node

    def parse_relationship_pattern(self) -> RelationshipPattern:
        """Parse ``-[:CALLS]->`` or ``<-[:IMPORTS]-`` or ``-`` (untyped).

        Direction:
          - ``-...->`` → right
          - ``<-...-`` → left
          - ``-...-``  → both (no arrow)
        """
        rel = RelationshipPattern()
        # Detect direction from the first token
        first = self.peek()
        if first is None:
            raise CypherParseError("expected relationship pattern but reached end of input")

        if first[0] == "LT":
            # ``<-...-`` → left
            self.advance()  # consume ``<``
            self.expect("DASH")
            rel.direction = "left"
        elif first[0] == "DASH":
            self.advance()  # consume ``-``
            rel.direction = "right"  # default; may be overridden if no ``>``
        else:
            raise CypherParseError(
                f"expected '-' or '<-' at start of relationship, got {first[0]} '{first[1]}'"
            )

        # Optional ``[:TYPE]``
        if self.peek() and self.peek()[0] == "LBRACKET":
            self.advance()  # consume ``[``
            # The tokenizer breaks ``[:`` into COLON + IDENT, so expect COLON
            self.expect("COLON")
            type_tok = self.expect("IDENT")
            rel.edge_type = type_tok[1].upper()
            self.expect("RBRACKET")

        # End of relationship: ``->`` or ``-``
        if rel.direction == "left":
            self.expect("DASH")
        else:
            # right or both — must end with ``->`` or ``-``
            tok = self.peek()
            if tok and tok[0] == "DASH":
                self.advance()
                # Optional ``>``
                if self.peek() and self.peek()[0] == "GT":
                    self.advance()
                    rel.direction = "right"
                else:
                    rel.direction = "both"
            elif tok and tok[0] == "GT":
                # ``->`` (the DASH was already consumed before [:TYPE])
                self.advance()
                rel.direction = "right"
            else:
                raise CypherParseError(
                    "relationship pattern must end with '->' or '-'"
                )

        return rel

    def parse_where_clauses(self) -> List[Union[Comparison, NotExistsPattern]]:
        """Parse a WHERE clause (single predicate for MVP — no AND/OR)."""
        predicates: List[Union[Comparison, NotExistsPattern]] = []
        predicates.append(self.parse_predicate())
        # MVP does NOT support AND / OR — if next token is AND, raise
        if self.is_keyword("AND") or self.is_keyword("OR"):
            tok = self.peek()
            raise CypherParseError(
                f"MVP does not support {tok[1]} — only a single WHERE predicate. "
                f"Use multiple queries or wait for follow-up PR."
            )
        return predicates

    def parse_predicate(self) -> Union[Comparison, NotExistsPattern]:
        """Parse one WHERE predicate."""
        if self.match_keyword("NOT"):
            # NOT EXISTS { ... }
            if not self.match_keyword("EXISTS"):
                raise CypherParseError("expected EXISTS after NOT")
            self.expect("LBRACE")
            path = self.parse_path_pattern()
            self.expect("RBRACE")
            return NotExistsPattern(path=path)

        if self.match_keyword("EXISTS"):
            # EXISTS { ... } — MVP treats this as "path exists" (positive).
            # Represented as NotExistsPattern with a negation flag? Simpler:
            # wrap in a Comparison-like? For MVP we only support NOT EXISTS,
            # so raise if someone writes EXISTS without NOT.
            raise CypherParseError(
                "MVP only supports NOT EXISTS, not EXISTS. "
                "Use a regular MATCH to test for existence."
            )

        # Otherwise: variable.property OP value
        var_tok = self.expect("IDENT")
        self.expect("DOT")
        prop_tok = self.expect("IDENT")
        # Now: =, !=, CONTAINS, IS NULL, IS NOT NULL
        tok = self.peek()
        if tok is None:
            raise CypherParseError("WHERE predicate must end with an operator + value")

        if tok[0] == "EQ":
            self.advance()
            value = self.parse_literal()
            return Comparison(
                variable=var_tok[1], property=prop_tok[1],
                operator="=", value=value,
            )
        if tok[0] == "NEQ":
            self.advance()
            value = self.parse_literal()
            return Comparison(
                variable=var_tok[1], property=prop_tok[1],
                operator="!=", value=value,
            )
        if tok[0] == "IDENT" and tok[1].upper() == "CONTAINS":
            self.advance()
            value = self.parse_literal()
            return Comparison(
                variable=var_tok[1], property=prop_tok[1],
                operator="CONTAINS", value=value,
            )
        if tok[0] == "IDENT" and tok[1].upper() == "IS":
            self.advance()
            if self.match_keyword("NOT"):
                self.expect("IDENT")  # NULL
                if self.tokens[self.pos - 1][1].upper() != "NULL":
                    raise CypherParseError("expected NULL after IS NOT")
                return Comparison(
                    variable=var_tok[1], property=prop_tok[1],
                    operator="IS NOT NULL", value=None,
                )
            else:
                self.expect("IDENT")  # NULL
                if self.tokens[self.pos - 1][1].upper() != "NULL":
                    raise CypherParseError("expected NULL after IS")
                return Comparison(
                    variable=var_tok[1], property=prop_tok[1],
                    operator="IS NULL", value=None,
                )
        raise CypherParseError(
            f"unsupported operator in WHERE: {tok[0]} '{tok[1]}' "
            f"(MVP supports =, !=, CONTAINS, IS NULL, IS NOT NULL)"
        )

    def parse_literal(self) -> Any:
        """Parse a string or number literal."""
        tok = self.peek()
        if tok is None:
            raise CypherParseError("expected literal value but reached end of input")
        if tok[0] == "STRING":
            self.advance()
            # Strip the surrounding quotes and unescape backslash-quotes
            raw = tok[1]
            quote = raw[0]
            inner = raw[1:-1]
            return inner.replace(f"\\{quote}", quote).replace("\\\\", "\\")
        if tok[0] == "NUMBER":
            self.advance()
            return int(tok[1])
        raise CypherParseError(
            f"MVP only supports string and number literals, got {tok[0]} '{tok[1]}'"
        )

    def parse_return_items(self) -> List[ReturnItem]:
        items: List[ReturnItem] = []
        items.append(self.parse_return_item())
        while self.peek() and self.peek()[0] == "COMMA":
            self.advance()
            items.append(self.parse_return_item())
        return items

    def parse_return_item(self) -> ReturnItem:
        var_tok = self.expect("IDENT")
        item = ReturnItem(variable=var_tok[1])
        if self.peek() and self.peek()[0] == "DOT":
            self.advance()
            prop_tok = self.expect("IDENT")
            item.property = prop_tok[1]
        return item


def parse_query(query: str) -> Query:
    """Parse a Cypher-subset query string into a :class:`Query` AST."""
    tokens = tokenize(query)
    if not tokens:
        raise CypherParseError("empty query")
    parser = _Parser(tokens)
    return parser.parse_query()


# ---------------------------------------------------------------------------
# Evaluator — runs the parsed Query against the SQLite graph tables
# ---------------------------------------------------------------------------

def _build_sql_for_query(q: Query, db_path: str) -> Tuple[str, List[Any]]:
    """Build a SQL query that materializes the MATCH + WHERE pattern.

    Returns ``(sql, params)``. The SQL returns one row per binding
    combination, with columns named after the bound variables.

    MVP limitation: only single-path MATCH (one chain of nodes + edges).
    Multiple MATCH clauses are not supported.
    """
    if len(q.match) != 1:
        raise CypherParseError(
            "MVP supports exactly one MATCH clause per query"
        )
    path = q.match[0]

    # Collect distinct bound variables (skip anonymous nodes whose
    # variable is "").
    bound_vars = [n.variable for n in path.nodes if n.variable]
    if not bound_vars:
        raise CypherParseError(
            "MATCH must bind at least one node variable (e.g. ``(f:Function)``)"
        )

    # Build SELECT clause from RETURN items
    select_parts: List[str] = []
    select_aliases: List[str] = []
    for ri in q.return_items:
        if ri.property:
            select_parts.append(f"{ri.variable}.{ri.property}")
            select_aliases.append(f"{ri.variable}_{ri.property}")
        else:
            # Return whole node — we'll fetch node_id + name + file + line + type
            select_parts.append(
                f"{ri.variable}.node_id AS {ri.variable}_node_id, "
                f"{ri.variable}.name AS {ri.variable}_name, "
                f"{ri.variable}.file AS {ri.variable}_file, "
                f"{ri.variable}.line AS {ri.variable}_line, "
                f"{ri.variable}.node_type AS {ri.variable}_node_type"
            )
            select_aliases.extend([
                f"{ri.variable}_node_id", f"{ri.variable}_name",
                f"{ri.variable}_file", f"{ri.variable}_line",
                f"{ri.variable}_node_type",
            ])

    # Build FROM clause: join graph_nodes + graph_edges per relationship
    from_parts: List[str] = []
    where_parts: List[str] = []
    params: List[Any] = []

    # First node
    first_node = path.nodes[0]
    from_parts.append(f"graph_nodes AS {first_node.variable or 'n0'}")
    if first_node.labels:
        # Node types in the SQLite graph are lowercase (function, class,
        # file, module, route, type, interface — see graph_model.py).
        # Cypher labels are conventionally PascalCase (Function, Class).
        # Normalize to lowercase so both ``:Function`` and ``:function``
        # match the same rows.
        normalized = [lbl.lower() for lbl in first_node.labels]
        placeholders = ",".join("?" for _ in normalized)
        where_parts.append(
            f"({first_node.variable or 'n0'}.node_type IN ({placeholders}))"
        )
        params.extend(normalized)

    # Walk relationships + nodes
    for i, rel in enumerate(path.relationships):
        node = path.nodes[i + 1]
        node_alias = node.variable or f"n{i + 1}"
        edge_alias = f"e{i}"

        from_parts.append(f"graph_edges AS {edge_alias}")
        from_parts.append(f"graph_nodes AS {node_alias}")

        # Edge direction
        if rel.direction == "right":
            # source = nodes[i], target = nodes[i+1]
            prev_alias = path.nodes[i].variable or f"n{i}"
            where_parts.append(f"{edge_alias}.source_id = {prev_alias}.node_id")
            where_parts.append(f"{edge_alias}.target_id = {node_alias}.node_id")
        elif rel.direction == "left":
            # source = nodes[i+1], target = nodes[i]
            prev_alias = path.nodes[i].variable or f"n{i}"
            where_parts.append(f"{edge_alias}.source_id = {node_alias}.node_id")
            where_parts.append(f"{edge_alias}.target_id = {prev_alias}.node_id")
        else:
            # "both" — match in either direction
            prev_alias = path.nodes[i].variable or f"n{i}"
            where_parts.append(
                f"(({edge_alias}.source_id = {prev_alias}.node_id "
                f"AND {edge_alias}.target_id = {node_alias}.node_id) "
                f"OR ({edge_alias}.source_id = {node_alias}.node_id "
                f"AND {edge_alias}.target_id = {prev_alias}.node_id))"
            )

        if rel.edge_type:
            # Edge types in SQLite are UPPERCASE (CALLS, IMPORTS, etc.)
            # — normalize to UPPERCASE so both ``:CALLS`` and ``:calls``
            # match.
            where_parts.append(f"{edge_alias}.edge_type = ?")
            params.append(rel.edge_type.upper())

        if node.labels:
            normalized = [lbl.lower() for lbl in node.labels]
            placeholders = ",".join("?" for _ in normalized)
            where_parts.append(f"({node_alias}.node_type IN ({placeholders}))")
            params.extend(normalized)

    # Add WHERE predicates
    for pred in q.where:
        if isinstance(pred, Comparison):
            if pred.operator == "=":
                where_parts.append(f"{pred.variable}.{pred.property} = ?")
                params.append(pred.value)
            elif pred.operator == "!=":
                where_parts.append(f"{pred.variable}.{pred.property} != ?")
                params.append(pred.value)
            elif pred.operator == "CONTAINS":
                where_parts.append(f"{pred.variable}.{pred.property} LIKE ?")
                params.append(f"%{pred.value}%")
            elif pred.operator == "IS NULL":
                where_parts.append(f"{pred.variable}.{pred.property} IS NULL")
            elif pred.operator == "IS NOT NULL":
                where_parts.append(f"{pred.variable}.{pred.property} IS NOT NULL")
        elif isinstance(pred, NotExistsPattern):
            # NOT EXISTS { (g)-[:CALLS]->(f) } — translate to a NOT EXISTS
            # subquery. The subquery selects a constant 1 from graph_edges
            # joined with graph_nodes, filtered by the path pattern.
            sub_path = pred.path
            if len(sub_path.nodes) != 2 or len(sub_path.relationships) != 1:
                raise CypherParseError(
                    "NOT EXISTS subquery MVP supports exactly one relationship"
                )
            sub_rel = sub_path.relationships[0]
            sub_src = sub_path.nodes[0]
            sub_tgt = sub_path.nodes[1]
            # The "outer" variable that the subquery references — typically
            # the target node (e.g. f in ``NOT EXISTS { (g)-[:CALLS]->(f) }``)
            # must be bound by the outer MATCH.
            if sub_tgt.variable:
                outer_var = sub_tgt.variable
            elif sub_src.variable:
                outer_var = sub_src.variable
            else:
                raise CypherParseError(
                    "NOT EXISTS subquery must reference an outer-bound variable"
                )

            # Build the subquery SQL
            if sub_rel.direction == "right":
                # (g)-[:CALLS]->(f)  →  exists when edge.source=g.node_id AND edge.target=f.node_id
                sub_sql = (
                    f"SELECT 1 FROM graph_edges se "
                    f"JOIN graph_nodes sn ON sn.node_id = se.source_id "
                    f"WHERE se.target_id = {outer_var}.node_id"
                )
            elif sub_rel.direction == "left":
                sub_sql = (
                    f"SELECT 1 FROM graph_edges se "
                    f"JOIN graph_nodes sn ON sn.node_id = se.target_id "
                    f"WHERE se.source_id = {outer_var}.node_id"
                )
            else:
                sub_sql = (
                    f"SELECT 1 FROM graph_edges se "
                    f"WHERE (se.source_id = {outer_var}.node_id "
                    f"OR se.target_id = {outer_var}.node_id)"
                )
            if sub_rel.edge_type:
                sub_sql += f" AND se.edge_type = ?"
                params.append(sub_rel.edge_type)
            where_parts.append(f"NOT EXISTS ({sub_sql})")

    sql = "SELECT DISTINCT " + ", ".join(select_parts)
    sql += " FROM " + " CROSS JOIN ".join(from_parts)
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if q.limit is not None:
        sql += f" LIMIT {q.limit}"

    return sql, params


def evaluate(q: Query, db_path: str) -> List[Dict[str, Any]]:
    """Run the parsed :class:`Query` against the SQLite graph tables.

    Returns a list of row dicts. Each row dict's keys are the return-item
    aliases (``f_name``, ``g_file``, etc.).

    Raises ``sqlite3.Error`` if the database or tables don't exist —
    callers should handle that case (the ``query_graph`` command catches
    it and returns an empty-result error payload).
    """
    sql, params = _build_sql_for_query(q, db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

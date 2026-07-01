"""
CodeLens — Semgrep-compatible rule matcher (Phase 1).

Given a parsed :class:`rule_pattern_parser.Rule` and a tree-sitter AST for a
Python source file, return a list of :class:`Match` objects.

The matcher walks the target AST in parallel with the pattern AST. It supports:

* ``pattern``           — AST shape equality, with metavariable capture
* ``pattern-regex``     — regex search on the source text of each candidate node
* ``pattern-not``       — exclude any match whose AST also matches the inner pattern
* ``pattern-either``    — OR across multiple child patterns

Metavariable semantics (Semgrep-compatible subset):

* ``$X`` (identifier-shaped)        — captures any single AST node
* ``$...ARGS`` (ellipsis-shaped)    — captures zero-or-more sibling nodes inside
  a sequence (e.g. argument list, tuple elements, decorator list)

The matcher is purely AST-based — no string-level tricks. It uses tree-sitter
for both pattern parsing and target parsing, so the matching semantics stay
consistent with the Python grammar.

File header — CodeLens rule engine (Phase 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from tree_sitter import Node, Parser

from rule_pattern_parser import Pattern, Rule


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Range:
    """Byte-range in source. Mirrors tree-sitter byte offsets."""

    start_byte: int
    end_byte: int
    start_point: tuple[int, int]  # (row, col) — 0-indexed
    end_point: tuple[int, int]

    @classmethod
    def from_node(cls, n: Node) -> "Range":
        return cls(
            start_byte=n.start_byte,
            end_byte=n.end_byte,
            start_point=n.start_point,
            end_point=n.end_point,
        )

    def contains(self, other: "Range") -> bool:
        return (
            self.start_byte <= other.start_byte and other.end_byte <= self.end_byte
        )


@dataclass(frozen=True)
class Match:
    """A single match of a rule against a target AST node."""

    rule_id: str
    range: Range
    severity: str
    message: str
    # Captured metavariables: name -> source-text snippet
    metavariables: dict[str, str] = field(default_factory=dict)
    # Optional: which pattern operator produced this match
    matched_by: str = ""


# ---------------------------------------------------------------------------
# Helpers for regex-seed matches (which don't have a real tree-sitter Node)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RangeWrapper:
    """Adapter so regex-seed matches can flow through the same code path
    as AST-seed matches. Only the ``range`` attribute is consumed."""

    range: Range


def _byte_offset_to_point(source_bytes: bytes, offset: int) -> tuple[int, int]:
    """Convert a byte offset to a (row, col) 0-indexed point."""
    if offset < 0:
        offset = 0
    if offset > len(source_bytes):
        offset = len(source_bytes)
    # Count newlines up to offset
    prefix = source_bytes[:offset]
    row = prefix.count(b"\n")
    last_nl = prefix.rfind(b"\n")
    if last_nl == -1:
        col = offset
    else:
        col = offset - (last_nl + 1)
    return (row, col)


# ---------------------------------------------------------------------------
# Pattern compilation — parse pattern source strings into tree-sitter trees
# ---------------------------------------------------------------------------


_PY_PARSER: Parser | None = None


def _get_parser() -> Parser:
    global _PY_PARSER
    if _PY_PARSER is None:
        import tree_sitter_python as tspython
        from tree_sitter import Language

        _PY_PARSER = Parser(Language(tspython.language()))
    return _PY_PARSER


_METAVAR_NAME_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")
_METAVAR_ELLIPSIS_RE = re.compile(r"^\$\.\.\.[A-Za-z_][A-Za-z0-9_]*$")


def _is_metavar(text: str) -> bool:
    return bool(_METAVAR_NAME_RE.match(text))


def _is_ellipsis(text: str) -> bool:
    return bool(_METAVAR_ELLIPSIS_RE.match(text))


def _strip_metavar(text: str) -> str:
    """$X -> X ; $...ARGS -> ...ARGS"""
    return text[1:]


# Pattern strings like `assert $X == True` are not standalone Python statements
# — tree-sitter-python will fail to parse them. We substitute metavars with
# placeholder expressions that we can recognize afterwards, then parse, then
# walk the resulting tree comparing placeholder nodes against metavar markers.

_PLACEHOLDER_PREFIX = "__codelens_mv_"


def _substitute_metavars(pattern_src: str) -> tuple[str, dict[str, str]]:
    """
    Replace $X and $...ARGS in pattern source with placeholder identifiers,
    return (rewritten_src, placeholder_map).
    """
    placeholder_map: dict[str, str] = {}

    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        # Try ellipsis first ($...NAME)
        if token.startswith("$..."):
            short = "ELL_" + token[4:]
        else:
            short = "MV_" + token[1:]
        # placeholder identifier — tree-sitter-python will treat as `identifier`
        placeholder = f"{_PLACEHOLDER_PREFIX}{short}"
        placeholder_map[placeholder] = token
        return placeholder

    # Match $...NAME first (longest), then $NAME
    rewritten = re.sub(r"\$\.\.\.[A-Za-z_][A-Za-z0-9_]*|\$[A-Za-z_][A-Za-z0-9_]*", _sub, pattern_src)
    return rewritten, placeholder_map


def _parse_pattern_source(src: str) -> tuple[Node, dict[str, str]]:
    """
    Parse a pattern source string into a tree-sitter node, returning
    (root_node, placeholder_map). The root node is the first named child
    of the synthesized module so callers can match against the actual
    pattern statement/expression rather than the wrapper.

    Semgrep-compat: when the pattern parses as an `expression_statement`
    wrapping a single expression (e.g. `eval($X)` → expr_stmt > call),
    we drill into the inner expression so that the pattern can match
    `call` nodes nested inside other statements (e.g. `x = eval('1+1')`).
    """
    rewritten, placeholder_map = _substitute_metavars(src)
    # Wrap in a trivial module so tree-sitter-python parses happily
    tree = _get_parser().parse(rewritten.encode("utf-8"))
    root = tree.root_node
    # If there was a parse error at the top level, raise — patterns should
    # be syntactically valid Python (modulo metavar substitution)
    if root.has_error:
        raise ValueError(
            f"pattern failed to parse as Python (after metavar substitution): {src!r}"
        )
    # Drill into the first named child of `module` so we get the actual
    # statement / expression node, not the module wrapper.
    named_children = [c for c in root.children if c.is_named]
    if not named_children:
        return root, placeholder_map
    pattern_node = named_children[0]
    # Semgrep-compat: drill expression_statement → inner expression so that
    # `pattern: eval($X)` matches the `call` node nested in `x = eval('1+1')`.
    if pattern_node.type == "expression_statement":
        inner = [c for c in pattern_node.children if c.is_named]
        if len(inner) == 1:
            pattern_node = inner[0]
    return pattern_node, placeholder_map


# ---------------------------------------------------------------------------
# AST matcher
# ---------------------------------------------------------------------------


class _Binding:
    """Mutable metavariable binding state for one match attempt."""

    __slots__ = ("single", "ellipsis")

    def __init__(self) -> None:
        self.single: dict[str, Node] = {}
        self.ellipsis: dict[str, list[Node]] = {}

    def clone(self) -> "_Binding":
        b = _Binding()
        b.single = dict(self.single)
        b.ellipsis = {k: list(v) for k, v in self.ellipsis.items()}
        return b


def _placeholder_to_metavar(text: str) -> str | None:
    if not text.startswith(_PLACEHOLDER_PREFIX):
        return None
    short = text[len(_PLACEHOLDER_PREFIX):]
    if short.startswith("ELL_"):
        return "$..." + short[4:]
    if short.startswith("MV_"):
        return "$" + short[3:]
    return None


def _node_is_metavar(node: Node, placeholder_map: dict[str, str]) -> str | None:
    """
    If `node` is an identifier whose text is one of our placeholders,
    return the original metavar token ($X or $...NAME). Otherwise None.
    """
    if node.type != "identifier":
        return None
    text = node.text.decode("utf-8", errors="replace")
    if text in placeholder_map:
        return placeholder_map[text]
    # Defensive: also handle placeholder-shape identifiers we didn't pre-map
    # (shouldn't happen, but cheap to check)
    mv = _placeholder_to_metavar(text)
    if mv is not None:
        return mv
    return None


def _node_is_ellipsis_metavar(node: Node, placeholder_map: dict[str, str]) -> str | None:
    """Return the original $...NAME token if `node` represents one."""
    mv = _node_is_metavar(node, placeholder_map)
    if mv is not None and _is_ellipsis(mv):
        return mv
    return None


def _node_is_single_metavar(node: Node, placeholder_map: dict[str, str]) -> str | None:
    """Return the original $NAME token if `node` represents one."""
    mv = _node_is_metavar(node, placeholder_map)
    if mv is not None and _is_metavar(mv):
        return mv
    return None


def _match_node(
    pattern: Node,
    target: Node,
    placeholder_map: dict[str, str],
    binding: _Binding,
) -> bool:
    """
    Recursively match `pattern` against `target`. Returns True on success.
    Mutates `binding` in-place on success.
    """
    # --- single metavar capture -------------------------------------------
    mv_single = _node_is_single_metavar(pattern, placeholder_map)
    if mv_single is not None:
        prev = binding.single.get(mv_single)
        if prev is None:
            binding.single[mv_single] = target
            return True
        # Repeated metavar: must match same source text
        return prev.text == target.text

    # --- ellipsis metavar ($...NAME) --------------------------------------
    # An ellipsis metavar as a *direct child* of a sequence is handled by the
    # caller in _match_children. If we get here, the ellipsis is in a position
    # where it has to match a single node — degrade gracefully to "zero match"
    # (i.e. only succeeds if the ellipsis is also in an "any-list" context).
    mv_ellipsis = _node_is_ellipsis_metavar(pattern, placeholder_map)
    if mv_ellipsis is not None:
        # Treat as zero-or-one capture of the target if it's a list-like slot
        # — but since we can't tell, capture the single node and let the
        # sequence matcher handle the rest elsewhere.
        prev = binding.ellipsis.get(mv_ellipsis)
        if prev is None:
            binding.ellipsis[mv_ellipsis] = [target]
            return True
        return [n.text for n in prev] == [target.text]

    # --- type check -------------------------------------------------------
    if pattern.type != target.type:
        return False

    # --- leaf node: compare text -----------------------------------------
    if pattern.child_count == 0:
        if target.child_count == 0:
            return pattern.text == target.text
        # pattern is a leaf but target has children — mismatch unless pattern
        # is a punctuation node
        return pattern.text == target.text

    # --- recurse into children with ellipsis support ---------------------
    return _match_children(pattern, target, placeholder_map, binding)


def _match_children(
    pattern: Node,
    target: Node,
    placeholder_map: dict[str, str],
    binding: _Binding,
) -> bool:
    """
    Match children of `pattern` against children of `target`, supporting
    $...NAME ellipsis metavars that consume zero-or-more siblings.
    """
    p_children = [c for c in pattern.children]
    t_children = [c for c in target.children]

    # Find ellipsis positions in pattern children
    ellipsis_indices = [
        i
        for i, c in enumerate(p_children)
        if _node_is_ellipsis_metavar(c, placeholder_map) is not None
    ]

    if not ellipsis_indices:
        # Simple case: same number of children, match one-to-one
        if len(p_children) != len(t_children):
            # tree-sitter often includes punctuation tokens; allow match if
            # the *named* children match and anon children line up by text
            return _match_children_strict(p_children, t_children, placeholder_map, binding)
        for pc, tc in zip(p_children, t_children):
            if not _match_node(pc, tc, placeholder_map, binding):
                return False
        return True

    if len(ellipsis_indices) > 1:
        # Phase 1 limitation: at most one ellipsis per sequence
        return False

    ell_idx = ellipsis_indices[0]
    ell_node = p_children[ell_idx]
    ell_var = _node_is_ellipsis_metavar(ell_node, placeholder_map)
    assert ell_var is not None

    # Children before the ellipsis must match prefix of target children
    prefix = p_children[:ell_idx]
    suffix = p_children[ell_idx + 1:]

    # Filter out anonymous punctuation tokens that don't appear in both lists
    # in the same positions — we treat them leniently (tree-sitter emits
    # '(' ')' ',' as anonymous nodes; both pattern and target have them).
    if len(prefix) > len(t_children) or len(suffix) > len(t_children) - len(prefix):
        return False

    # Match prefix
    for i, pc in enumerate(prefix):
        if not _match_node(pc, t_children[i], placeholder_map, binding):
            return False

    # Match suffix
    consumed_t_start = len(prefix)
    consumed_t_end = len(t_children) - len(suffix)
    if consumed_t_end < consumed_t_start:
        return False

    for i, pc in enumerate(suffix):
        tc = t_children[consumed_t_end + i]
        if not _match_node(pc, tc, placeholder_map, binding):
            return False

    # Capture ellipsis slice
    captured = t_children[consumed_t_start:consumed_t_end]
    prev = binding.ellipsis.get(ell_var)
    if prev is None:
        binding.ellipsis[ell_var] = captured
    else:
        # Same ellipsis used twice — require identical source-text sequence
        if [n.text for n in prev] != [n.text for n in captured]:
            return False
    return True


def _match_children_strict(
    p_children: list[Node],
    t_children: list[Node],
    placeholder_map: dict[str, str],
    binding: _Binding,
) -> bool:
    """
    Lenient child matcher that allows pattern and target to differ in
    anonymous punctuation tokens (e.g. trailing commas, parentheses that
    tree-sitter sometimes emits differently). We align named children
    strictly and accept anonymous children if their text matches or
    if both are punctuation.
    """
    p_named = [c for c in p_children if c.is_named]
    t_named = [c for c in t_children if c.is_named]
    if len(p_named) != len(t_named):
        return False
    # Walk both children lists in order, skipping anon tokens on either side
    pi = ti = 0
    while pi < len(p_children) and ti < len(t_children):
        pc = p_children[pi]
        tc = t_children[ti]
        if not pc.is_named and not tc.is_named:
            if pc.text != tc.text:
                return False
            pi += 1
            ti += 1
            continue
        if not pc.is_named:
            # skip pattern-side anon if target-side has a named node here
            pi += 1
            continue
        if not tc.is_named:
            ti += 1
            continue
        if not _match_node(pc, tc, placeholder_map, binding):
            return False
        pi += 1
        ti += 1
    # consume trailing anon on either side
    while pi < len(p_children) and not p_children[pi].is_named:
        pi += 1
    while ti < len(t_children) and not t_children[ti].is_named:
        ti += 1
    return pi == len(p_children) and ti == len(t_children)


# ---------------------------------------------------------------------------
# Per-rule evaluation
# ---------------------------------------------------------------------------


def _walk_all_nodes(root: Node) -> Iterable[Node]:
    """Pre-order traversal of every node in the AST (named + anonymous)."""
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        # Push children in reverse so we visit them in source order
        for c in reversed(n.children):
            stack.append(c)


def _collect_metavar_values(binding: _Binding, source_bytes: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, n in binding.single.items():
        out[k] = source_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
    for k, nodes in binding.ellipsis.items():
        out[k] = ", ".join(
            source_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
            for n in nodes
        )
    return out


def _match_pattern_op(
    pattern: Pattern,
    target_node: Node,
    source_bytes: bytes,
) -> list[_Binding]:
    """
    Evaluate one pattern operator against one candidate target node.
    Returns a list of bindings (possibly empty).
    """
    if pattern.kind == "pattern":
        try:
            pattern_root, placeholder_map = _parse_pattern_source(pattern.value)
        except ValueError:
            return []
        binding = _Binding()
        if _match_node(pattern_root, target_node, placeholder_map, binding):
            return [binding]
        return []

    if pattern.kind == "pattern-regex":
        regex: re.Pattern = pattern.value
        text = source_bytes[
            target_node.start_byte:target_node.end_byte
        ].decode("utf-8", errors="replace")
        if regex.search(text):
            return [_Binding()]
        return []

    if pattern.kind == "pattern-either":
        results: list[_Binding] = []
        for child in pattern.value:
            results.extend(_match_pattern_op(child, target_node, source_bytes))
        return results

    raise ValueError(f"unsupported pattern kind in match: {pattern.kind}")


def _matches_pattern_at_any_node(
    pattern_src: str,
    target_root: Node,
    source_bytes: bytes,
) -> list[tuple[Node, _Binding]]:
    """Find all (node, binding) pairs where pattern_src matches."""
    try:
        pattern_root, placeholder_map = _parse_pattern_source(pattern_src)
    except ValueError:
        return []
    out: list[tuple[Node, _Binding]] = []
    for n in _walk_all_nodes(target_root):
        binding = _Binding()
        if _match_node(pattern_root, n, placeholder_map, binding):
            out.append((n, binding))
    return out


def evaluate_rule(rule: Rule, tree: Any, source_bytes: bytes) -> list[Match]:
    """
    Evaluate one rule against a parsed tree-sitter tree.

    Parameters
    ----------
    rule
        Parsed rule from :mod:`rule_pattern_parser`.
    tree
        A ``tree_sitter.Tree`` (or any object with a ``root_node`` attribute).
    source_bytes
        The raw source bytes the tree was parsed from — needed for
        ``pattern-regex`` and for metavariable value extraction.

    Returns
    -------
    list[Match]
        One Match per (target_node × binding) that satisfies all patterns.
    """
    root: Node = tree.root_node if hasattr(tree, "root_node") else tree
    matches: list[Match] = []

    # Separate operators: positive (pattern / pattern-regex / pattern-either)
    # vs negative (pattern-not).
    positive: list[Pattern] = []
    negatives: list[Pattern] = []
    for p in rule.patterns:
        if p.kind == "pattern-not":
            negatives.append(p)
        else:
            positive.append(p)

    if not positive:
        # Rule with only pattern-not — undefined in Semgrep. Skip.
        return matches

    # For each candidate target node, evaluate the positive patterns.
    # Phase 1 semantics:
    #   - If the first positive op is a `pattern`, we anchor on its matches
    #     (the rule fires on the AST span that the first `pattern` matched).
    #   - All other positive ops must also match at the same node (AND).
    #   - pattern-not must NOT match at any descendant of the candidate node.
    first_op = positive[0]
    other_ops = positive[1:]

    # Generate (candidate_node, binding) seeds from the first operator.
    if first_op.kind == "pattern":
        seeds = _matches_pattern_at_any_node(first_op.value, root, source_bytes)
    elif first_op.kind == "pattern-regex":
        # Regex matches against the entire file source (Semgrep-compat:
        # pattern-regex is line/file-level, not AST-level). Each regex
        # hit becomes one seed; the matched range is the regex match span.
        seeds = []
        regex: re.Pattern = first_op.value
        text = source_bytes.decode("utf-8", errors="replace")
        for m in regex.finditer(text):
            # Build a synthetic "node-like" Range object so downstream
            # Match construction works without fabricating a tree-sitter Node.
            r = Range(
                start_byte=m.start(),
                end_byte=m.end(),
                start_point=_byte_offset_to_point(source_bytes, m.start()),
                end_point=_byte_offset_to_point(source_bytes, m.end()),
            )
            seeds.append((_RangeWrapper(r), _Binding()))
    elif first_op.kind == "pattern-either":
        seeds = []
        for child in first_op.value:
            if child.kind == "pattern":
                seeds.extend(_matches_pattern_at_any_node(child.value, root, source_bytes))
            else:  # pattern-regex
                r: re.Pattern = child.value
                text = source_bytes.decode("utf-8", errors="replace")
                for m in r.finditer(text):
                    rng = Range(
                        start_byte=m.start(),
                        end_byte=m.end(),
                        start_point=_byte_offset_to_point(source_bytes, m.start()),
                        end_point=_byte_offset_to_point(source_bytes, m.end()),
                    )
                    seeds.append((_RangeWrapper(rng), _Binding()))
    else:
        return matches

    for node, binding in seeds:
        # AND with remaining positive ops — they must all match at the same node
        ok = True
        for op in other_ops:
            # For regex seeds (which are _RangeWrapper), only pattern-regex
            # AND-ops make sense; pattern ops would require an AST node.
            if isinstance(node, _RangeWrapper):
                if op.kind != "pattern-regex":
                    ok = False
                    break
                regex_op: re.Pattern = op.value
                text = source_bytes[node.range.start_byte:node.range.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if not regex_op.search(text):
                    ok = False
                    break
                continue
            sub_results = _match_pattern_op(op, node, source_bytes)
            if not sub_results:
                ok = False
                break
            # If sub_results returned multiple bindings, we keep the first one
            # (Phase 1 does not unify across multiple AND branches).
            extra = sub_results[0]
            # Merge single bindings — ellipsis bindings are kept per-branch
            for k, v in extra.single.items():
                if k not in binding.single:
                    binding.single[k] = v
                elif binding.single[k].text != v.text:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue

        # Apply pattern-not exclusions: if any inner pattern matches at the
        # same node or a descendant, drop this candidate.
        excluded = False
        for neg in negatives:
            inner_src = neg.value
            if isinstance(node, _RangeWrapper):
                # Regex seed — pattern-not on a regex match is unusual but
                # we support it by checking if inner_src regex matches the
                # same span text.
                try:
                    inner_re = re.compile(inner_src)
                except re.error:
                    continue
                text = source_bytes[node.range.start_byte:node.range.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if inner_re.search(text):
                    excluded = True
                    break
            else:
                neg_matches = _matches_pattern_at_any_node(inner_src, node, source_bytes)
                if neg_matches:
                    excluded = True
                    break
        if excluded:
            continue

        mv_values = _collect_metavar_values(binding, source_bytes)
        # Use the wrapped Range if the seed is a regex _RangeWrapper.
        rng = node.range if isinstance(node, _RangeWrapper) else Range.from_node(node)
        matches.append(
            Match(
                rule_id=rule.id,
                range=rng,
                severity=rule.severity,
                message=rule.message,
                metavariables=mv_values,
                matched_by=first_op.kind,
            )
        )

    # De-duplicate matches with identical (start_byte, end_byte, rule_id)
    seen: set[tuple[int, int, str]] = set()
    deduped: list[Match] = []
    for m in matches:
        key = (m.range.start_byte, m.range.end_byte, m.rule_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    return deduped


def evaluate_rules(
    rules: Iterable[Rule],
    tree: Any,
    source_bytes: bytes,
) -> list[Match]:
    """Evaluate multiple rules against the same tree."""
    out: list[Match] = []
    for r in rules:
        out.extend(evaluate_rule(r, tree, source_bytes))
    return out


# ---------------------------------------------------------------------------
# Convenience: parse + match in one shot
# ---------------------------------------------------------------------------


def parse_python(source: str | bytes) -> Any:
    """Parse a Python source string and return the tree-sitter Tree."""
    if isinstance(source, str):
        source = source.encode("utf-8")
    return _get_parser().parse(source)


def match_source(
    rules: Iterable[Rule],
    source: str | bytes,
) -> list[Match]:
    """Parse source + run all rules + return matches."""
    if isinstance(source, str):
        source_bytes = source.encode("utf-8")
    else:
        source_bytes = source
    tree = _get_parser().parse(source_bytes)
    return evaluate_rules(rules, tree, source_bytes)

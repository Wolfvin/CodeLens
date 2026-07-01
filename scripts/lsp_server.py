"""
CodeLens — Native LSP 3.17 server.

Exposes CodeLens analysis (tree-sitter scan + rule engine + minimal
symbol graph) to editors such as Neovim, Emacs, Helix, VS Code via
the Language Server Protocol.

Phase 1 supported methods:

* ``initialize`` / ``initialized`` / ``shutdown`` / ``exit``
  (mostly handled by pygls base class)
* ``textDocument/didOpen``     — parse + scan, publish diagnostics
* ``textDocument/didChange``   — re-parse + re-scan
* ``textDocument/hover``       — return symbol info + callers/callees
* ``textDocument/definition``  — go-to-definition via symbol graph

Severity mapping (CodeLens → LSP ``DiagnosticSeverity``):

    critical → Error   (1)
    high     → Warning (2)
    medium   → Information (3)
    low      → Hint    (4)
    INFO     → Information (3)
    WARNING  → Warning (2)
    ERROR    → Error   (1)
    HINT     → Hint    (4)

The server is launched by the ``codelens lsp`` command (see
``scripts/commands/lsp.py``) over stdio by default. TCP is also supported
via ``--tcp --port`` for debugging.

File header — CodeLens LSP server (Phase 1).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from tree_sitter import Node, Parser

# ---------------------------------------------------------------------------
# Symbol graph — minimal in-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """A symbol extracted from a Python source file."""

    name: str
    kind: str  # "function" | "class" | "variable" | "parameter" | "import"
    file_uri: str
    range: "lsp.Range"
    # Source text of the defining node, used by hover
    source_text: str = ""
    # For functions/classes: list of (name, file_uri) call sites found
    # within the same file (Phase 1 — cross-file is out of scope).
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)


@dataclass
class DocumentState:
    """Per-document state: source text + symbol index + last diagnostics."""

    uri: str
    version: int
    source: str
    symbols: dict[str, Symbol] = field(default_factory=dict)
    # Index from byte offset → symbol name (for hover/definition lookup)
    offset_index: list[tuple[int, int, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

_CODELENS_SEVERITY_TO_LSP: dict[str, lsp.DiagnosticSeverity] = {
    "CRITICAL": lsp.DiagnosticSeverity.Error,
    "HIGH": lsp.DiagnosticSeverity.Warning,
    "MEDIUM": lsp.DiagnosticSeverity.Information,
    "LOW": lsp.DiagnosticSeverity.Hint,
    "ERROR": lsp.DiagnosticSeverity.Error,
    "WARNING": lsp.DiagnosticSeverity.Warning,
    "INFO": lsp.DiagnosticSeverity.Information,
    "HINT": lsp.DiagnosticSeverity.Hint,
}


def severity_to_lsp(sev: str) -> lsp.DiagnosticSeverity:
    """Map a CodeLens severity string to an LSP DiagnosticSeverity enum."""
    if not sev:
        return lsp.DiagnosticSeverity.Information
    return _CODELENS_SEVERITY_TO_LSP.get(sev.upper(), lsp.DiagnosticSeverity.Information)


# ---------------------------------------------------------------------------
# Tree-sitter parser (singleton)
# ---------------------------------------------------------------------------


_PY_PARSER: Parser | None = None


def _get_parser() -> Parser:
    global _PY_PARSER
    if _PY_PARSER is None:
        import tree_sitter_python as tspython
        from tree_sitter import Language

        _PY_PARSER = Parser(Language(tspython.language()))
    return _PY_PARSER


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


def uri_to_path(uri: str) -> str:
    """Convert a `file://` URI to a filesystem path."""
    if not uri:
        return ""
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        return unquote(parsed.path)
    return uri


def path_to_uri(path: str) -> str:
    """Convert a filesystem path to a `file://` URI."""
    abs_path = os.path.abspath(path)
    return "file://" + abs_path


def _byte_offset_to_point(source_bytes: bytes, offset: int) -> tuple[int, int]:
    """Convert a byte offset to a (row, col) 0-indexed point."""
    if offset < 0:
        offset = 0
    if offset > len(source_bytes):
        offset = len(source_bytes)
    prefix = source_bytes[:offset]
    row = prefix.count(b"\n")
    last_nl = prefix.rfind(b"\n")
    if last_nl == -1:
        col = offset
    else:
        col = offset - (last_nl + 1)
    return (row, col)


def _ts_point_to_lsp(ts_point: tuple[int, int]) -> lsp.Position:
    """tree-sitter (row, col) → LSP Position (0-indexed)."""
    return lsp.Position(line=ts_point[0], character=ts_point[1])


def _ts_node_to_lsp_range(node: Node) -> lsp.Range:
    return lsp.Range(
        start=_ts_point_to_lsp(node.start_point),
        end=_ts_point_to_lsp(node.end_point),
    )


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


def _extract_symbols(
    uri: str,
    source: str,
    tree: Any,
) -> DocumentState:
    """Walk the AST and build a symbol index for the given document."""
    state = DocumentState(uri=uri, version=0, source=source)
    root = tree.root_node if hasattr(tree, "root_node") else tree
    source_bytes = source.encode("utf-8")

    def _walk(node: Node) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = name_node.text.decode("utf-8", errors="replace")
                _register_symbol(
                    state,
                    Symbol(
                        name=name,
                        kind="function",
                        file_uri=uri,
                        range=_ts_node_to_lsp_range(node),
                        source_text=source_bytes[
                            node.start_byte:node.end_byte
                        ].decode("utf-8", errors="replace"),
                    ),
                )
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = name_node.text.decode("utf-8", errors="replace")
                _register_symbol(
                    state,
                    Symbol(
                        name=name,
                        kind="class",
                        file_uri=uri,
                        range=_ts_node_to_lsp_range(node),
                        source_text=source_bytes[
                            node.start_byte:node.end_byte
                        ].decode("utf-8", errors="replace"),
                    ),
                )
        elif node.type == "assignment":
            # Top-level / class-level variable assignment
            lhs = node.child_by_field_name("left")
            if lhs is not None and lhs.type == "identifier":
                name = lhs.text.decode("utf-8", errors="replace")
                _register_symbol(
                    state,
                    Symbol(
                        name=name,
                        kind="variable",
                        file_uri=uri,
                        range=_ts_node_to_lsp_range(node),
                        source_text=source_bytes[
                            node.start_byte:node.end_byte
                        ].decode("utf-8", errors="replace"),
                    ),
                )
        elif node.type == "import_statement":
            # Track imports as symbols so hover on an imported name can
            # at least tell the user "this is imported".
            for child in node.children:
                if child.type in {"dotted_name", "aliased_import"}:
                    text = child.text.decode("utf-8", errors="replace")
                    # Use the last segment as the symbol name
                    short = text.split(".")[-1].split(" as ")[-1].strip()
                    if short:
                        _register_symbol(
                            state,
                            Symbol(
                                name=short,
                                kind="import",
                                file_uri=uri,
                                range=_ts_node_to_lsp_range(child),
                                source_text=text,
                            ),
                        )
        for c in node.children:
            _walk(c)

    _walk(root)

    # Build callee/caller relationships: for each function definition,
    # find identifier references inside its body that match other symbols
    # in this document.
    _build_call_graph(state, root, source_bytes)
    return state


def _register_symbol(state: DocumentState, sym: Symbol) -> None:
    # First definition wins — shadowing within the same file is uncommon
    # for Phase 1; we keep the outermost definition.
    if sym.name not in state.symbols:
        state.symbols[sym.name] = sym
    # Update offset index for hover/definition lookup
    state.offset_index.append(
        (
            _lsp_position_to_byte(state.source, sym.range.start.line, sym.range.start.character),
            _lsp_position_to_byte(state.source, sym.range.end.line, sym.range.end.character),
            sym.name,
        )
    )


def _lsp_position_to_byte(source: str, line: int, character: int) -> int:
    """Convert LSP (line, character) to byte offset in source."""
    lines = source.split("\n")
    if line >= len(lines):
        return len(source.encode("utf-8"))
    prefix = "\n".join(lines[:line]) + "\n" if line > 0 else ""
    prefix_bytes = prefix.encode("utf-8")
    line_bytes = lines[line].encode("utf-8")[: max(0, character)]
    return len(prefix_bytes) + len(line_bytes)


def _build_call_graph(state: DocumentState, root: Node, source_bytes: bytes) -> None:
    """Populate ``callers`` / ``callees`` for each function symbol.

    Phase 1: only intra-file references. Cross-file taint/graph is
    out of scope — this minimal graph exists so that ``hover`` returns
    useful info even before the real CodeLens graph is wired in.
    """
    # For each function_definition node, walk its body and record any
    # identifier whose name matches another known symbol.
    def _walk_functions(node: Node) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if name_node is not None and body_node is not None:
                fn_name = name_node.text.decode("utf-8", errors="replace")
                _collect_call_refs(state, fn_name, body_node)
        for c in node.children:
            _walk_functions(c)

    _walk_functions(root)


def _collect_call_refs(state: DocumentState, fn_name: str, body: Node) -> None:
    """Walk `body` looking for call expressions whose function name
    matches a known symbol — record them as callees of `fn_name`."""
    sym = state.symbols.get(fn_name)
    if sym is None:
        return

    def _walk_call(node: Node) -> None:
        if node.type == "call":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                callee_name = fn.text.decode("utf-8", errors="replace")
                if callee_name in state.symbols and callee_name != fn_name:
                    if callee_name not in sym.callees:
                        sym.callees.append(callee_name)
                    # Back-reference: callee has fn_name as a caller
                    callee_sym = state.symbols[callee_name]
                    if fn_name not in callee_sym.callers:
                        callee_sym.callers.append(fn_name)
        for c in node.children:
            _walk_call(c)

    _walk_call(body)


# ---------------------------------------------------------------------------
# Scan — produce diagnostics
# ---------------------------------------------------------------------------


def _scan_for_diagnostics(
    source: str,
    rule_files: list[str],
) -> list[lsp.Diagnostic]:
    """Run the rule engine on `source` and return LSP diagnostics."""
    if not rule_files:
        return []
    try:
        # Import lazily so the LSP server can start even if the rule
        # engine module is unavailable (e.g. minimal install).
        from rule_engine import load_rules
        from rule_matcher import match_source
    except ImportError:
        return []

    rules, errors = load_rules(rule_files)
    if errors or not rules:
        return []

    matches = match_source(rules, source)
    out: list[lsp.Diagnostic] = []
    for m in matches:
        out.append(
            lsp.Diagnostic(
                range=lsp.Range(
                    start=lsp.Position(
                        line=m.range.start_point[0],
                        character=m.range.start_point[1],
                    ),
                    end=lsp.Position(
                        line=m.range.end_point[0],
                        character=m.range.end_point[1],
                    ),
                ),
                message=m.message,
                severity=severity_to_lsp(m.severity),
                source="codelens",
                code=m.rule_id,
            )
        )
    return out


# ---------------------------------------------------------------------------
# The LanguageServer subclass
# ---------------------------------------------------------------------------


class CodeLensLanguageServer(LanguageServer):
    """CodeLens LSP server.

    Holds per-document state in ``self._documents`` and an optional
    list of rule files for diagnostics.
    """

    def __init__(self, name: str = "codelens", version: str = "0.1.0") -> None:
        super().__init__(name, version)
        self._documents: dict[str, DocumentState] = {}
        self._rule_files: list[str] = []
        # If True, scan even when no rule files are configured (basic checks
        # like syntax errors only — Phase 1 stub).
        self._basic_checks_enabled: bool = True

    def set_rule_files(self, rule_files: list[str]) -> None:
        self._rule_files = list(rule_files)

    # --- document management ----------------------------------------------

    def _update_document(self, uri: str, source: str, version: int) -> DocumentState:
        tree = _get_parser().parse(source.encode("utf-8"))
        state = _extract_symbols(uri, source, tree)
        state.version = version
        self._documents[uri] = state
        return state

    def _publish_diagnostics(self, uri: str) -> None:
        state = self._documents.get(uri)
        if state is None:
            self.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )
            return
        diagnostics = _scan_for_diagnostics(state.source, self._rule_files)
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    # --- symbol lookup ----------------------------------------------------

    def _symbol_at(self, uri: str, position: lsp.Position) -> Symbol | None:
        state = self._documents.get(uri)
        if state is None:
            return None
        byte_offset = _lsp_position_to_byte(
            state.source, position.line, position.character
        )
        # Walk the offset index to find the symbol whose range contains
        # the cursor. We prefer the smallest such range.
        best: Symbol | None = None
        best_span = -1
        for start, end, name in state.offset_index:
            if start <= byte_offset <= end:
                span = end - start
                if best is None or span < best_span or best_span == -1:
                    best = state.symbols.get(name)
                    best_span = span
        return best

    def _symbol_named(self, uri: str, name: str) -> Symbol | None:
        state = self._documents.get(uri)
        if state is None:
            return None
        return state.symbols.get(name)

    # --- hover content ----------------------------------------------------

    def _hover_text(self, sym: Symbol) -> str:
        lines: list[str] = []
        lines.append(f"**{sym.kind}** `{sym.name}`")
        lines.append("")
        lines.append(f"- file: `{sym.file_uri}`")
        lines.append(f"- range: line {sym.range.start.line + 1}, col {sym.range.start.character + 1}")
        if sym.callers:
            lines.append(f"- callers: {', '.join(sorted(set(sym.callers)))}")
        if sym.callees:
            lines.append(f"- callees: {', '.join(sorted(set(sym.callees)))}")
        # Show first 5 lines of source for context
        src_lines = sym.source_text.split("\n")[:5]
        if len(src_lines) > 0:
            lines.append("")
            lines.append("```python")
            for sl in src_lines:
                lines.append(sl)
            if len(sym.source_text.split("\n")) > 5:
                lines.append("...")
            lines.append("```")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature handlers
# ---------------------------------------------------------------------------


def build_server(rule_files: list[str] | None = None) -> CodeLensLanguageServer:
    """Construct a CodeLensLanguageServer with all feature handlers wired."""
    server = CodeLensLanguageServer(name="codelens", version="0.1.0")
    if rule_files:
        server.set_rule_files(rule_files)

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    def _did_open(ls: CodeLensLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        ls._update_document(params.text_document.uri, params.text_document.text, params.text_document.version)
        ls._publish_diagnostics(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    def _did_change(
        ls: CodeLensLanguageServer,
        params: lsp.DidChangeTextDocumentParams,
    ) -> None:
        # Apply incremental changes to the in-memory source
        state = ls._documents.get(params.text_document.uri)
        if state is None:
            # No prior state — skip (editor should have sent didOpen first)
            return
        new_source = state.source
        # Apply changes in order. Each change has a range; if range is None
        # the whole document is replaced.
        for change in params.content_changes:
            if change.range is None:
                new_source = change.text
                continue
            start_byte = _lsp_position_to_byte(
                new_source, change.range.start.line, change.range.start.character
            )
            end_byte = _lsp_position_to_byte(
                new_source, change.range.end.line, change.range.end.character
            )
            new_source = (
                new_source.encode("utf-8")[:start_byte].decode("utf-8", errors="replace")
                + change.text
                + new_source.encode("utf-8")[end_byte:].decode("utf-8", errors="replace")
            )
        ls._update_document(params.text_document.uri, new_source, params.text_document.version)
        ls._publish_diagnostics(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    def _hover(ls: CodeLensLanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
        t0 = time.monotonic()
        sym = ls._symbol_at(params.text_document.uri, params.position)
        if sym is None:
            return None
        # Hover range = symbol's defining range, so the editor can highlight it
        text = ls._hover_text(sym)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        # Log if we exceed the 50ms budget — Phase 1 graph is in-memory so
        # this should never trip, but the instrumentation is here for the
        # real-graph integration later.
        if elapsed_ms > 50.0:
            ls.show_message_log(
                f"codelens lsp: hover took {elapsed_ms:.1f}ms (>50ms budget)",
                lsp.MessageType.Warning,
            )
        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value=text,
            ),
            range=sym.range,
        )

    @server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
    def _definition(
        ls: CodeLensLanguageServer,
        params: lsp.DefinitionParams,
    ) -> lsp.Definition | None:
        # Phase 1: try to find the symbol under the cursor; if it's a
        # known symbol in the same document, jump to its definition.
        state = ls._documents.get(params.text_document.uri)
        if state is None:
            return None
        # Find the identifier under the cursor by re-parsing the source
        # and locating the smallest identifier node containing the position.
        tree = _get_parser().parse(state.source.encode("utf-8"))
        target_node = _find_identifier_at(tree.root_node, state.source, params.position)
        if target_node is None:
            return None
        name = target_node.text.decode("utf-8", errors="replace")
        sym = ls._symbol_named(params.text_document.uri, name)
        if sym is None:
            return None
        return lsp.Location(uri=sym.file_uri, range=sym.range)

    # NOTE: We deliberately do NOT register a custom INITIALIZE handler.
    # pygls auto-builds ServerCapabilities from the registered @feature
    # handlers above. Adding a custom INITIALIZE that returns a hand-built
    # InitializeResult would *override* the auto-built capabilities and
    # drop hover/definition from the advertisement.

    return server


def _find_identifier_at(
    root: Node,
    source: str,
    position: lsp.Position,
) -> Node | None:
    """Find the smallest `identifier` AST node containing `position`."""
    target_offset = _lsp_position_to_byte(source, position.line, position.character)
    best: Node | None = None
    best_span = -1

    def _walk(n: Node) -> None:
        nonlocal best, best_span
        if (
            n.start_byte <= target_offset <= n.end_byte
            and n.type == "identifier"
        ):
            span = n.end_byte - n.start_byte
            if best is None or span < best_span or best_span == -1:
                best = n
                best_span = span
        for c in n.children:
            _walk(c)

    _walk(root)
    return best


# ---------------------------------------------------------------------------
# Entrypoint — used by scripts/commands/lsp.py
# ---------------------------------------------------------------------------


def run_stdio(rule_files: list[str] | None = None) -> None:
    """Start the LSP server over stdio (the default transport)."""
    server = build_server(rule_files)
    server.start_io()


def run_tcp(host: str, port: int, rule_files: list[str] | None = None) -> None:
    """Start the LSP server over TCP (useful for debugging)."""
    server = build_server(rule_files)
    server.start_tcp(host, port)

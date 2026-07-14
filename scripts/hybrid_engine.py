"""
Hybrid Analysis Engine for CodeLens — Combines fast regex/AST with deep LSP analysis.

Confidence Levels:
- high: LSP verified (find-references confirmed, type inferred)
- medium: AST matched, no LSP contradiction
- low: Regex-only heuristic, no LSP/AST corroboration
"""

import os
import sys
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from lsp_client import (
    detect_available_servers, get_server_for_file, get_server_for_workspace,
    get_connection_pool, shutdown_pool, _uri_to_path, LSPClient,
)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def compute_confidence(
    fast_path_hit: bool,
    lsp_verified: Optional[bool] = None,
    ast_matched: bool = False,
    lsp_contradicts: bool = False,
) -> str:
    if lsp_contradicts:
        return CONFIDENCE_LOW
    if lsp_verified is True:
        return CONFIDENCE_HIGH
    if lsp_verified is None:
        return CONFIDENCE_MEDIUM if ast_matched else CONFIDENCE_LOW
    return CONFIDENCE_MEDIUM if ast_matched else CONFIDENCE_LOW


def compute_confidence_distribution(findings: List[Dict]) -> Dict[str, int]:
    dist = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        confidence = f.get("confidence", CONFIDENCE_LOW)
        dist[confidence] = dist.get(confidence, 0) + 1
    return dist


class HybridEngine:
    """Orchestrates fast-path + deep-path analysis with merge logic."""

    def __init__(self, workspace: str, deep: bool = False):
        self.workspace = os.path.abspath(workspace)
        self.deep = deep
        self._lsp_available: Optional[bool] = None
        self._available_servers: Dict[str, Dict] = {}
        self._workspace_server: Optional[Tuple[str, Dict]] = None
        self._opened_files: Set[str] = set()

        if self.deep:
            self._available_servers = detect_available_servers()
            self._workspace_server = get_server_for_workspace(self.workspace)
            self._lsp_available = any(
                info["available"] for info in self._available_servers.values()
            )
            if not self._lsp_available:
                print(
                    "[CodeLens] --deep: No LSP servers found. "
                    "Falling back to regex/AST analysis. "
                    "Install an LSP server for deeper analysis (run: codelens --lsp-status).",
                    file=sys.stderr,
                )

    @property
    def lsp_active(self) -> bool:
        return self.deep and self._lsp_available is True

    def get_lsp_client(self, file_path: str = None) -> Optional[LSPClient]:
        if not self.lsp_active:
            return None
        pool = get_connection_pool()
        if file_path:
            return pool.get_client_for_file(self.workspace, file_path)
        if self._workspace_server:
            return pool.get_client(self.workspace, self._workspace_server[0])
        return None

    def open_file_for_lsp(self, file_path: str) -> None:
        if not self.lsp_active:
            return
        abs_path = os.path.abspath(file_path)
        if abs_path in self._opened_files:
            return
        client = self.get_lsp_client(abs_path)
        if client:
            client.open_file(abs_path)
            self._opened_files.add(abs_path)

    def close_all_lsp_files(self) -> None:
        if not self.lsp_active:
            return
        for file_path in self._opened_files:
            client = self.get_lsp_client(file_path)
            if client:
                client.close_file(file_path)
        self._opened_files.clear()

    def get_diagnostics(self, file_path: str, wait_timeout: float = 3.0) -> Optional[List[Dict]]:
        """Return LSP diagnostics for ``file_path`` (issue #253).

        Returns ``None`` if LSP is not active (server not installed or
        ``--deep`` off) so the caller can distinguish "no LSP" from "LSP
        ran and found nothing" (empty list). Never raises.
        """
        if not self.lsp_active:
            return None
        client = self.get_lsp_client(os.path.abspath(file_path))
        if not client:
            return None
        try:
            return client.get_diagnostics(os.path.abspath(file_path), wait_timeout=wait_timeout)
        except Exception:
            return None

    def cleanup(self) -> None:
        self.close_all_lsp_files()

    # ─── Dead-Code Deep Verification ──────────────────────────

    def verify_dead_code(self, findings: List[Dict]) -> List[Dict]:
        """Use LSP find-references to verify dead-code findings."""
        if not self.lsp_active or not findings:
            for f in findings:
                if "confidence" not in f:
                    f["confidence"] = CONFIDENCE_MEDIUM
            return findings

        for finding in findings:
            file_path = finding.get("file", "")
            line = finding.get("line", 0)
            name = finding.get("name", finding.get("function", ""))

            if not file_path or not line:
                finding["confidence"] = CONFIDENCE_LOW
                finding["lsp_verified"] = False
                continue

            self.open_file_for_lsp(file_path)
            client = self.get_lsp_client(file_path)
            if not client:
                finding["confidence"] = CONFIDENCE_LOW
                finding["lsp_verified"] = False
                continue

            char = self._find_symbol_char(file_path, line, name)
            if char is None:
                char = 0
            lsp_line = max(0, line - 1)

            refs = client.find_references(file_path, lsp_line, char, include_declaration=False)
            external_refs = self._filter_external_references(refs, file_path, lsp_line, char)

            if external_refs:
                finding["confidence"] = CONFIDENCE_LOW
                finding["lsp_verified"] = True
                finding["lsp_references_found"] = len(external_refs)
                finding["false_positive_likely"] = True
            else:
                finding["confidence"] = CONFIDENCE_HIGH
                finding["lsp_verified"] = True
                finding["lsp_references_found"] = 0
                finding["false_positive_likely"] = False

        return findings

    # ─── Query Deep Verification ──────────────────────────────

    def enhance_query(self, result: Dict, query_name: str) -> Dict:
        """Use LSP go-to-definition to enhance query results."""
        if not self.lsp_active:
            result["confidence"] = CONFIDENCE_MEDIUM
            return result

        node = result.get("node", {})
        file_path = node.get("file", "")
        line = node.get("line", 0)

        if not file_path or not line:
            result["confidence"] = CONFIDENCE_LOW
            return result

        self.open_file_for_lsp(file_path)
        client = self.get_lsp_client(file_path)
        if not client:
            result["confidence"] = CONFIDENCE_LOW
            return result

        lsp_line = max(0, line - 1)
        fn_name = node.get("fn", query_name)
        char = self._find_symbol_char(file_path, line, fn_name)
        if char is None:
            char = 0

        definitions = client.go_to_definition(file_path, lsp_line, char)
        if definitions:
            defn = definitions[0]
            defn_uri = defn.get("uri", "")
            defn_path = _uri_to_path(defn_uri) if defn_uri else ""
            defn_range = defn.get("range", {})
            defn_start = defn_range.get("start", {})

            result["lsp_definition"] = {
                "file": defn_path,
                "line": defn_start.get("line", 0) + 1,
                "character": defn_start.get("character", 0),
            }
            if _paths_match(defn_path, file_path):
                result["confidence"] = CONFIDENCE_HIGH
            else:
                result["confidence"] = CONFIDENCE_MEDIUM
                result["lsp_alternative_definition"] = defn_path
        else:
            result["confidence"] = CONFIDENCE_MEDIUM

        type_info = client.get_type_info(file_path, lsp_line, char)
        if type_info:
            result["lsp_type"] = type_info.strip()

        return result

    # ─── Impact Deep Verification ─────────────────────────────

    def enhance_impact(self, result: Dict, symbol_name: str) -> Dict:
        """Use LSP find-references to enhance impact analysis."""
        if not self.lsp_active:
            result["confidence"] = CONFIDENCE_MEDIUM
            return result

        node_info = result.get("affected", {})
        all_affected = node_info.get("direct", []) + node_info.get("indirect", [])
        defn_file, defn_line = self._find_symbol_definition(symbol_name)

        if not defn_file or not defn_line:
            result["confidence"] = CONFIDENCE_LOW
            return result

        self.open_file_for_lsp(defn_file)
        client = self.get_lsp_client(defn_file)
        if not client:
            result["confidence"] = CONFIDENCE_LOW
            return result

        lsp_line = max(0, defn_line - 1)
        char = self._find_symbol_char(defn_file, defn_line, symbol_name)
        if char is None:
            char = 0

        refs = client.find_references(defn_file, lsp_line, char, include_declaration=True)

        if refs:
            lsp_refs = []
            for ref in refs:
                ref_uri = ref.get("uri", "")
                ref_path = _uri_to_path(ref_uri) if ref_uri else ""
                ref_range = ref.get("range", {})
                ref_start = ref_range.get("start", {})
                ref_line = ref_start.get("line", 0) + 1
                if ref_path.endswith(defn_file) and ref_line == defn_line:
                    continue
                lsp_refs.append({"file": ref_path, "line": ref_line,
                                 "character": ref_start.get("character", 0), "source": "lsp"})

            existing_refs = set()
            for item in all_affected:
                existing_refs.add((item.get("file", ""), item.get("line", 0)))

            new_refs = []
            for ref in lsp_refs:
                if (ref["file"], ref["line"]) not in existing_refs:
                    new_refs.append({
                        "type": "function", "name": symbol_name,
                        "file": ref["file"], "line": ref["line"],
                        "relation": f"references {symbol_name} (LSP-verified)",
                        "source": "lsp", "domain": "backend",
                    })

            if new_refs:
                node_info["direct"].extend(new_refs)
                stats = result.get("stats", {})
                stats["lsp_additional_references"] = len(new_refs)
                stats["direct_dependents"] = stats.get("direct_dependents", 0) + len(new_refs)
                result["stats"] = stats

            result["lsp_references_total"] = len(lsp_refs)
            result["confidence"] = CONFIDENCE_HIGH
        else:
            result["confidence"] = CONFIDENCE_MEDIUM

        return result

    # ─── Smell / Complexity Deep Verification ─────────────────

    def enhance_smell(self, findings: List[Dict]) -> List[Dict]:
        if not self.lsp_active or not findings:
            for f in findings:
                if "confidence" not in f:
                    f["confidence"] = CONFIDENCE_MEDIUM
            return findings
        for finding in findings:
            file_path = finding.get("file", "")
            line = finding.get("line", 0)
            if not file_path or not line:
                finding["confidence"] = CONFIDENCE_LOW
                continue
            self.open_file_for_lsp(file_path)
            client = self.get_lsp_client(file_path)
            if not client:
                finding["confidence"] = CONFIDENCE_LOW
                continue
            lsp_line = max(0, line - 1)
            type_info = client.get_type_info(file_path, lsp_line, 0)
            if type_info:
                finding["lsp_type_info"] = type_info.strip()[:200]
                finding["confidence"] = CONFIDENCE_HIGH
            else:
                finding["confidence"] = CONFIDENCE_MEDIUM
        return findings

    def enhance_complexity(self, findings: List[Dict]) -> List[Dict]:
        if not self.lsp_active or not findings:
            for f in findings:
                if "confidence" not in f:
                    f["confidence"] = CONFIDENCE_MEDIUM
            return findings
        for finding in findings:
            file_path = finding.get("file", "")
            line = finding.get("line", 0)
            name = finding.get("name", finding.get("function", ""))
            if not file_path or not line:
                finding["confidence"] = CONFIDENCE_LOW
                continue
            self.open_file_for_lsp(file_path)
            client = self.get_lsp_client(file_path)
            if not client:
                finding["confidence"] = CONFIDENCE_LOW
                continue
            lsp_line = max(0, line - 1)
            char = self._find_symbol_char(file_path, line, name)
            if char is None:
                char = 0
            type_info = client.get_type_info(file_path, lsp_line, char)
            if type_info:
                finding["lsp_signature"] = type_info.strip()[:200]
                finding["confidence"] = CONFIDENCE_HIGH
            else:
                finding["confidence"] = CONFIDENCE_MEDIUM
        return findings

    # ─── Helper Methods ───────────────────────────────────────

    def _find_symbol_char(self, file_path: str, line: int, symbol_name: str) -> Optional[int]:
        try:
            abs_path = os.path.abspath(file_path)
            if not os.path.exists(abs_path):
                return None
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if line < 1 or line > len(lines):
                return None
            line_text = lines[line - 1]
            idx = line_text.find(symbol_name)
            if idx >= 0:
                return idx
            match = re.compile(r'\b' + re.escape(symbol_name) + r'\b').search(line_text)
            return match.start() if match else None
        except Exception:
            return None

    def _filter_external_references(self, refs, source_file, source_line, source_char):
        external = []
        source_path = os.path.abspath(source_file)
        for ref in refs:
            ref_uri = ref.get("uri", "")
            ref_path = _uri_to_path(ref_uri) if ref_uri else ""
            ref_range = ref.get("range", {})
            ref_start = ref_range.get("start", {})
            if _paths_match(ref_path, source_path):
                if ref_start.get("line") == source_line and ref_start.get("character") == source_char:
                    continue
            external.append(ref)
        return external

    def _find_symbol_definition(self, symbol_name: str) -> Tuple[Optional[str], Optional[int]]:
        try:
            from registry import load_backend_registry
            backend = load_backend_registry(self.workspace)
            for node in backend.get("nodes", []):
                if node.get("fn") == symbol_name:
                    return node.get("file"), node.get("line", 0)
        except Exception:
            pass
        return None, None

    def find_references_for_symbol(self, symbol_name: str) -> Optional[List[Dict]]:
        """Resolve ``symbol_name`` to its definition, then ask the LSP server
        for its references (issue #255 — LSP-backed trace-up precision).

        Reuses the existing ``lsp_client.find_references`` +
        ``_find_symbol_definition`` + ``_find_symbol_char`` machinery — no new
        LSP infrastructure. Returns a list of reference dicts::

            {"file": <abs path>, "line": <1-indexed>, "character": <int>}

        excluding the definition site itself (the caller wants callers, not the
        declaration). Returns ``None`` when LSP is not active or the symbol
        cannot be resolved/located, so the caller can distinguish "no LSP path"
        from "LSP ran and found zero references" (empty list). Never raises.
        """
        if not self.lsp_active:
            return None
        def_file, def_line = self._find_symbol_definition(symbol_name)
        if not def_file or not def_line:
            return None
        abs_def = def_file if os.path.isabs(def_file) else os.path.join(self.workspace, def_file)
        if not os.path.exists(abs_def):
            return None
        self.open_file_for_lsp(abs_def)
        client = self.get_lsp_client(abs_def)
        if not client:
            return None
        char = self._find_symbol_char(abs_def, def_line, symbol_name)
        if char is None:
            char = 0
        lsp_line = max(0, def_line - 1)
        try:
            raw = client.find_references(abs_def, lsp_line, char, include_declaration=False)
        except Exception:
            return None
        if raw is None:
            return None
        external = self._filter_external_references(raw, abs_def, lsp_line, char)
        out: List[Dict] = []
        for ref in external:
            ref_uri = ref.get("uri", "")
            ref_path = _uri_to_path(ref_uri) if ref_uri else ""
            start = ref.get("range", {}).get("start", {})
            out.append({
                "file": ref_path,
                "line": start.get("line", 0) + 1,   # LSP 0-indexed -> report 1-indexed
                "character": start.get("character", 0),
            })
        return out


def _paths_match(path_a: str, path_b: str) -> bool:
    """Compare two file paths for equality using normalized absolute paths.

    Uses os.path.samefile() when both paths exist, otherwise falls back to
    comparing os.path.normcase(os.path.abspath(...)) to avoid false matches
    from loose endswith() checks (e.g., 'utils.py' matching 'my_utils.py').
    """
    if not path_a or not path_b:
        return False
    try:
        if os.path.exists(path_a) and os.path.exists(path_b):
            return os.path.samefile(path_a, path_b)
    except (OSError, ValueError):
        pass
    # Fallback: normalize and compare absolute paths
    norm_a = os.path.normcase(os.path.abspath(path_a))
    norm_b = os.path.normcase(os.path.abspath(path_b))
    return norm_a == norm_b


def create_hybrid_engine(workspace: str, deep: bool = False) -> HybridEngine:
    return HybridEngine(workspace, deep=deep)


def get_lsp_status() -> Dict[str, Any]:
    servers = detect_available_servers()
    available_count = sum(1 for info in servers.values() if info["available"])
    return {
        "status": "ok",
        "lsp_available": available_count > 0,
        "available_count": available_count,
        "total_servers": len(servers),
        "servers": servers,
        "recommendation": (
            "LSP integration active. Use --deep for enhanced analysis."
            if available_count > 0
            else "No LSP servers found. Install one for --deep analysis. "
                 "Recommended: pyright (Python) or typescript-language-server (JS/TS)."
        ),
    }


def add_confidence_to_result(result: Dict, findings_key: str = None) -> Dict:
    if not isinstance(result, dict):
        return result
    all_findings = []
    if findings_key and findings_key in result:
        val = result[findings_key]
        if isinstance(val, list):
            all_findings.extend(val)
        elif isinstance(val, dict):
            for sub_val in val.values():
                if isinstance(sub_val, list):
                    all_findings.extend(sub_val)
    else:
        for key in ("findings", "results", "items", "direct", "indirect",
                     "functions", "leaks", "hints", "issues", "violations"):
            val = result.get(key)
            if isinstance(val, list):
                all_findings.extend(val)
            elif isinstance(val, dict):
                for sub_val in val.values():
                    if isinstance(sub_val, list):
                        all_findings.extend(sub_val)
    if all_findings:
        for f in all_findings:
            if isinstance(f, dict) and "confidence" not in f:
                f["confidence"] = CONFIDENCE_MEDIUM
        dist = compute_confidence_distribution(all_findings)
        if "stats" not in result:
            result["stats"] = {}
        result["stats"]["confidence_distribution"] = dist
    return result

# @WHO:   scripts/formatters/graphml.py
# @WHAT:  GraphML XML output formatter for graph-producing commands
# @PART:  formatters
# @ENTRY: format_graphml()
"""
GraphML Output Formatter for CodeLens — issue #59 Phase 3.

Emits GraphML 1.0 XML (https://graphml.graphdrawing.org/) so CodeLens graph
output opens directly in Gephi, Cytoscape, yEd, Neo4j, and any other tool
that consumes the GraphML schema.

Per-command graph extraction
----------------------------
- ``scan``     — full call graph from SQLite (``graph_nodes`` + ``graph_edges``)
- ``trace``    — subgraph from ``chains.up`` + ``chains.down`` (callers/callees)
- ``impact``   — subgraph from ``affected.direct`` + ``affected.indirect``
- ``circular`` — subgraph from every detected cycle (function/import/css)
- other        — single-node placeholder graph (command name + warning attr)

The formatter is registered as a global ``--format graphml`` choice, so every
CLI command and MCP tool can request GraphML. Commands that do not produce
graph data still get a valid (single-node) GraphML document, never an error.

@FLOW:   GRAPHML_FORMAT
@CALLS:  _extract_scan_graph() -> SQLite graph_nodes/graph_edges
@CALLS:  _extract_trace_graph() / _extract_impact_graph() / _extract_circular_graph()
@MUTATES: none (pure formatter — reads SQLite read-only, writes XML string)
"""

import os
import sqlite3
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# GraphML namespace — required for schema validity. Tools like Gephi accept
# both namespaced and non-namespaced GraphML, but the spec mandates the
# namespace. We register the default namespace so the serialized output
# does not carry ugly ``ns0:`` prefixes.
GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
ET.register_namespace("", GRAPHML_NS)


# ─── Public Entry Point ──────────────────────────────────────


def format_graphml(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output as a GraphML XML string.

    Args:
        data:    The command result dict (or list/scalar — coerced to placeholder).
        command: CLI command name (``scan``, ``trace``, ``impact``, ``circular`` …).
        workspace: Absolute path to workspace root — used by the scan extractor
                   to locate the SQLite database at
                   ``<workspace>/.codelens/codelens.db``.

    Returns:
        UTF-8 XML string conforming to the GraphML 1.0 schema. Always
        well-formed; never raises. On extraction failure the returned
        document is a single-node placeholder graph carrying a ``warning``
        data attribute describing the failure.
    """
    try:
        nodes, edges = _extract_graph(data, command, workspace)
    except Exception as exc:  # pragma: no cover — defensive, formatter must not crash CLI
        nodes = [{
            "id": "codelens:error",
            "name": command or "codelens",
            "type": "error",
            "warning": f"GraphML extraction failed: {exc}",
        }]
        edges = []

    if not nodes:
        nodes = [{
            "id": "codelens:empty",
            "name": command or "codelens",
            "type": "empty",
            "warning": "No graph data available for this command.",
        }]

    return _serialize_graphml(nodes, edges)


# ─── Graph Extraction (per command) ─────────────────────────


def _extract_graph(
    data: Any, command: str, workspace: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Dispatch to the per-command extractor and return (nodes, edges).

    Each node dict has at minimum an ``id`` field. Common optional fields
    are ``name``, ``type``, ``file``, ``line``, ``warning``. Each edge dict
    has ``source``, ``target`` and optional ``kind``, ``cycle_id``,
    ``relation``. The serializer maps these to GraphML ``<data>`` elements.
    """
    if not isinstance(data, dict):
        return _extract_default_graph(data, command)

    extractor = _EXTRACTORS.get(command)
    if extractor is None:
        return _extract_default_graph(data, command)
    return extractor(data, workspace)


def _extract_scan_graph(
    data: Dict[str, Any], workspace: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Read the full call graph from SQLite ``graph_nodes``/``graph_edges``.

    Falls back to a single-node placeholder if the database is missing,
    the graph tables are empty, or SQLite is unavailable. The placeholder
    carries the scan stats from ``data`` so the user still sees something
    useful when opening the file in Gephi.
    """
    if not workspace:
        return _placeholder("scan", data, "Workspace path not provided.")

    db_path = _resolve_db_path(workspace)
    if not db_path or not os.path.exists(db_path):
        return _placeholder(
            "scan", data,
            f"SQLite database not found at {db_path}. Run `codelens scan` first.",
        )

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Defensive: tables may not exist if scan was never run.
            table_check = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('graph_nodes', 'graph_edges')"
            ).fetchall()
            if len(table_check) < 2:
                return _placeholder(
                    "scan", data,
                    "Graph tables not initialized. Run `codelens scan` first.",
                )

            for row in conn.execute(
                "SELECT node_id, node_type, name, file, line "
                "FROM graph_nodes"
            ):
                nodes.append({
                    "id": row["node_id"],
                    "name": row["name"] or row["node_id"],
                    "type": row["node_type"] or "node",
                    "file": row["file"] or "",
                    "line": row["line"] or 0,
                })

            for row in conn.execute(
                "SELECT source_id, target_id, edge_type "
                "FROM graph_edges WHERE target_id IS NOT NULL AND target_id != ''"
            ):
                edges.append({
                    "source": row["source_id"],
                    "target": row["target_id"],
                    "kind": row["edge_type"] or "edge",
                })
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _placeholder("scan", data, f"SQLite read failed: {exc}")

    if not nodes:
        return _placeholder(
            "scan", data,
            "Graph tables exist but contain no nodes. Run `codelens scan` first.",
        )

    return nodes, edges


def _extract_trace_graph(
    data: Dict[str, Any], _workspace: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a subgraph from ``trace`` command's ``chains.up``/``chains.down``.

    Each chain entry is a dict with ``node_id``, ``fn``, ``file``, ``line``,
    ``depth``, ``direction``, ``path``. We synthesize directed edges between
    consecutive entries in each chain — direction is preserved (up=caller→root,
    down=root→callee) so the resulting graph opens correctly in Gephi with
    arrows pointing along the call direction.
    """
    symbol = data.get("symbol", "")
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    chains = data.get("chains") or {}

    # Always include the queried symbol as a node, even if no chains found.
    if symbol:
        nodes[symbol] = {
            "id": symbol,
            "name": symbol,
            "type": "query_symbol",
        }

    for direction, entries in chains.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            nid = entry.get("node_id") or entry.get("id") or entry.get("fn") or ""
            if not nid or nid == "unresolved":
                # Unresolved external calls have no node_id — synthesize
                # an external node so the edge still has a target/source.
                fn = entry.get("fn") or entry.get("to_fn") or "unresolved"
                nid = f"external:{fn}"
                nodes[nid] = {
                    "id": nid,
                    "name": fn,
                    "type": "external",
                    "resolved": False,
                }
            else:
                nodes.setdefault(nid, {
                    "id": nid,
                    "name": entry.get("fn") or nid,
                    "type": "function",
                    "file": entry.get("file") or "",
                    "line": entry.get("line") or 0,
                    "depth": entry.get("depth"),
                    "direction": entry.get("direction"),
                })

    # Build edges between consecutive entries in each chain. Each chain is a
    # flat list — not a tree path — so edges represent "appears next in BFS
    # expansion". For ``up`` chains the edge direction is caller→callee (root
    # symbol is at the end), for ``down`` it is callee→caller (root symbol is
    # at the start). We add a direction-labeled edge so consumers can filter.
    for direction, entries in chains.items():
        if not isinstance(entries, list) or len(entries) < 2:
            continue
        for i in range(len(entries) - 1):
            src = _entry_id(entries[i])
            dst = _entry_id(entries[i + 1])
            if not src or not dst:
                continue
            edges.append({
                "source": src,
                "target": dst,
                "kind": "calls",
                "direction": direction,
            })

    return list(nodes.values()), edges


def _extract_impact_graph(
    data: Dict[str, Any], _workspace: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a subgraph from ``impact`` command's affected.direct/indirect.

    The queried symbol is the root node. Each direct dependent is connected
    to the root with a ``direct`` edge. Each indirect dependent is connected
    to the root with an ``indirect`` edge (transitive depth > 1).
    """
    symbol = data.get("symbol", "")
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    if symbol:
        nodes.append({
            "id": f"root:{symbol}",
            "name": symbol,
            "type": "query_symbol",
        })

    affected = data.get("affected") or {}
    root_id = f"root:{symbol}" if symbol else ""

    for bucket, label in (("direct", "direct"), ("indirect", "indirect")):
        items = affected.get(bucket)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            if not name:
                continue
            nid = f"{bucket}:{name}:{item.get('file', '')}:{item.get('line', 0)}"
            nodes.append({
                "id": nid,
                "name": name,
                "type": item.get("type") or "function",
                "file": item.get("file") or "",
                "line": item.get("line") or 0,
                "relation": item.get("relation") or "",
                "domain": item.get("domain") or "",
                "bucket": bucket,
            })
            if root_id:
                edges.append({
                    "source": root_id,
                    "target": nid,
                    "kind": label,
                    "relation": item.get("relation") or "",
                })

    return nodes, edges


def _extract_circular_graph(
    data: Dict[str, Any], _workspace: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a subgraph from every cycle detected by ``circular``.

    Each cycle's chain is rendered as a closed loop — edges connect
    consecutive chain entries plus a closing edge from the last entry back
    to the first. Each cycle gets a stable ``cycle_id`` so Gephi can color
    cycles distinctly via edge partitioning.
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    cycles_by_cat = data.get("cycles") or {}
    cycle_index = 0

    for category, cycle_list in cycles_by_cat.items():
        if not isinstance(cycle_list, list):
            continue
        for cycle in cycle_list:
            if not isinstance(cycle, dict):
                continue
            chain = cycle.get("chain") or []
            if not isinstance(chain, list) or len(chain) < 1:
                continue

            cycle_id = f"{category}#{cycle_index}"
            cycle_index += 1
            severity = cycle.get("severity", "")
            cycle_type = cycle.get("type", category)

            # Materialize chain nodes.
            node_ids: List[str] = []
            for entry in chain:
                if not isinstance(entry, dict):
                    continue
                nid = entry.get("id") or entry.get("node_id") or entry.get("fn") or ""
                if not nid:
                    continue
                node_ids.append(nid)
                nodes.setdefault(nid, {
                    "id": nid,
                    "name": entry.get("fn") or nid,
                    "type": "function",
                    "file": entry.get("file") or "",
                    "line": entry.get("line") or 0,
                })

            # Build cycle edges. circular_engine convention: the chain already
            # includes the closing node (chain[0] == chain[-1]) when the cycle
            # has length >= 2 — e.g. ``[foo, bar, foo]`` represents the cycle
            # ``foo → bar → foo``. In that case we emit edges between
            # consecutive entries only (no wrap-around), otherwise we add a
            # closing edge from the last entry back to the first. Recursion
            # (len == 1) is rendered as a self-loop.
            if len(node_ids) >= 2:
                closes_explicitly = node_ids[0] == node_ids[-1]
                limit = len(node_ids) - 1 if closes_explicitly else len(node_ids)
                for i in range(limit):
                    src = node_ids[i]
                    dst = node_ids[(i + 1) % len(node_ids)]
                    edges.append({
                        "source": src,
                        "target": dst,
                        "kind": "cycle_edge",
                        "cycle_id": cycle_id,
                        "cycle_type": cycle_type,
                        "category": category,
                        "severity": severity,
                    })
            elif len(node_ids) == 1:
                # Recursion (self-loop).
                edges.append({
                    "source": node_ids[0],
                    "target": node_ids[0],
                    "kind": "cycle_edge",
                    "cycle_id": cycle_id,
                    "cycle_type": cycle_type,
                    "category": category,
                    "severity": severity,
                })

    return list(nodes.values()), edges


def _extract_default_graph(
    data: Any, command: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fallback extractor: single-node placeholder graph.

    Used when the command does not naturally produce a graph (e.g. ``init``,
    ``doctor``, ``secrets``). The placeholder carries the command name and a
    warning attribute so users opening the file in Gephi understand why they
    see only one node. We also surface the result status as a data attribute
    so machine consumers can introspect without re-running the command.
    """
    status = ""
    if isinstance(data, dict):
        status = data.get("status", "")

    warning = (
        f"Command '{command or 'codelens'}' does not produce graph data. "
        f"Use --format graphml with: scan, trace, impact, circular."
    )

    node = {
        "id": f"codelens:{command or 'default'}",
        "name": command or "codelens",
        "type": "placeholder",
        "warning": warning,
    }
    if status:
        node["status"] = status

    return [node], []


# ─── Helpers ─────────────────────────────────────────────────


_EXTRACTORS = {
    "scan": _extract_scan_graph,
    "trace": _extract_trace_graph,
    "impact": _extract_impact_graph,
    "circular": _extract_circular_graph,
}


def _resolve_db_path(workspace: str) -> Optional[str]:
    """Resolve the SQLite db path for the workspace, honoring utils.default_db_path.

    Uses the project's single source of truth when available; falls back to
    ``<workspace>/.codelens/codelens.db`` if utils is not importable (e.g.
    when the formatter is exercised from outside the scripts/ directory).
    """
    try:
        from utils import default_db_path
        return default_db_path(workspace)
    except Exception:
        return os.path.join(workspace, ".codelens", "codelens.db")


def _placeholder(
    command: str, data: Any, warning: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a single-node placeholder carrying scan stats as data attrs."""
    node: Dict[str, Any] = {
        "id": f"codelens:{command}",
        "name": command,
        "type": "placeholder",
        "warning": warning,
    }
    if isinstance(data, dict):
        stats = data.get("stats")
        if isinstance(stats, dict):
            node["stats"] = "; ".join(f"{k}={v}" for k, v in stats.items())
    return [node], []


def _entry_id(entry: Dict[str, Any]) -> str:
    """Stable node id for a trace chain entry (handles unresolved nodes)."""
    nid = entry.get("node_id") or entry.get("id") or ""
    if nid and nid != "unresolved":
        return nid
    fn = entry.get("fn") or entry.get("to_fn") or "unresolved"
    return f"external:{fn}"


# ─── GraphML Serialization ───────────────────────────────────


# Attribute key definitions — emitted as <key> elements at the top of the
# document so consumers know the schema. IDs are stable (d0..d8) so the
# same writer always produces byte-identical output for the same input.
_NODE_KEYS = [
    ("d0", "name", "string"),
    ("d1", "type", "string"),
    ("d2", "file", "string"),
    ("d3", "line", "int"),
    ("d4", "warning", "string"),
    ("d5", "status", "string"),
    ("d6", "stats", "string"),
    ("d7", "depth", "int"),
    ("d8", "direction", "string"),
    ("d9", "relation", "string"),
    ("d10", "domain", "string"),
    ("d11", "bucket", "string"),
    ("d12", "resolved", "boolean"),
]

_EDGE_KEYS = [
    ("e0", "kind", "string"),
    ("e1", "direction", "string"),
    ("e2", "cycle_id", "string"),
    ("e3", "cycle_type", "string"),
    ("e4", "category", "string"),
    ("e5", "severity", "string"),
    ("e6", "relation", "string"),
]


def _serialize_graphml(
    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
) -> str:
    """Serialize nodes+edges to a GraphML 1.0 XML string.

    The output is pretty-printed (indented) for human readability and
    round-trips cleanly through ``xml.etree.ElementTree.fromstring``.
    """
    root = ET.Element(f"{{{GRAPHML_NS}}}graphml")

    # <key> declarations
    for key_id, attr_name, attr_type in _NODE_KEYS:
        ET.SubElement(root, f"{{{GRAPHML_NS}}}key", {
            "id": key_id,
            "for": "node",
            "attr.name": attr_name,
            "attr.type": attr_type,
        })
    for key_id, attr_name, attr_type in _EDGE_KEYS:
        ET.SubElement(root, f"{{{GRAPHML_NS}}}key", {
            "id": key_id,
            "for": "edge",
            "attr.name": attr_name,
            "attr.type": attr_type,
        })

    graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph", {
        "id": "G",
        "edgedefault": "directed",
    })

    # <node> elements
    for node in nodes:
        node_el = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {
            "id": str(node.get("id", "")),
        })
        _attach_data(node_el, node, _NODE_KEYS)

    # <edge> elements
    for edge in edges:
        edge_el = ET.SubElement(graph, f"{{{GRAPHML_NS}}}edge", {
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
        })
        _attach_data(edge_el, edge, _EDGE_KEYS)

    # Pretty-print with indentation. ElementTree.indent was added in 3.9;
    # fall back to minidom for older Pythons (project supports 3.8 per
    # pyproject.toml).
    if hasattr(ET, "indent"):
        ET.indent(root, space="  ")
        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    else:  # pragma: no cover — Python 3.8 fallback
        from xml.dom import minidom
        rough = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(rough)
        xml_bytes = parsed.toprettyxml(indent="  ", encoding="utf-8")

    return xml_bytes.decode("utf-8") if isinstance(xml_bytes, bytes) else xml_bytes


def _attach_data(
    parent: ET.Element,
    attrs: Dict[str, Any],
    key_defs: List[Tuple[str, str, str]],
) -> None:
    """Attach ``<data>`` children for every attribute that is present.

    Skips ``None`` values and the ``id`` field (which is the XML attribute,
    not a data child). Booleans are serialized as ``true``/``false`` per the
    GraphML spec; integers as their decimal string form.
    """
    for key_id, attr_name, _attr_type in key_defs:
        if attr_name not in attrs:
            continue
        val = attrs[attr_name]
        if val is None:
            continue
        if isinstance(val, bool):
            text = "true" if val else "false"
        else:
            text = str(val)
        data_el = ET.SubElement(parent, f"{{{GRAPHML_NS}}}data", {"key": key_id})
        data_el.text = text

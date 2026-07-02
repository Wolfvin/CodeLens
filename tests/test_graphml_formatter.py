"""Tests for the GraphML output formatter (issue #59 Phase 3).

Covers:
- All four graph-producing commands (scan, trace, impact, circular)
- Placeholder fallback for non-graph commands
- Edge cases: empty chains, missing SQLite db, recursion, missing db tables
- GraphML XML validity (parses, has correct namespace, well-formed)
- Structure correctness: nodes/edges present, attributes attached
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from formatters import format_output
from formatters.graphml import (
    format_graphml,
    _extract_circular_graph,
    _extract_default_graph,
    _extract_impact_graph,
    _extract_scan_graph,
    _extract_trace_graph,
    _serialize_graphml,
)


GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
NS = {"g": GRAPHML_NS}


def _parse(xml_str):
    """Parse GraphML XML, raising AssertionError with snippet on failure."""
    try:
        return ET.fromstring(xml_str)
    except ET.ParseError as exc:
        raise AssertionError(f"GraphML XML is not well-formed: {exc}\n---\n{xml_str[:500]}\n---")


def _counts(xml_str):
    """Return (node_count, edge_count, key_count) for a GraphML XML string."""
    root = _parse(xml_str)
    return (
        len(root.findall(".//g:node", NS)),
        len(root.findall(".//g:edge", NS)),
        len(root.findall("./g:key", NS)),
    )


def _is_valid_graphml_root(root):
    """Verify root element is <graphml> in the GraphML namespace."""
    return root.tag == f"{{{GRAPHML_NS}}}graphml"


# ─── 1. Format dispatch — graphml is a registered format ─────


class TestFormatDispatch(unittest.TestCase):
    """format_output('graphml', ...) routes to format_graphml."""

    def test_format_output_routes_to_graphml(self):
        out = format_output({"status": "ok"}, "graphml", command="scan", workspace="/tmp")
        root = _parse(out)
        self.assertTrue(_is_valid_graphml_root(root))

    def test_graphml_choice_appears_in_cli_help(self):
        """The CLI's --format choices list must include 'graphml'.

        We import codelens.py as a module is impractical (it would execute
        argparse setup); instead we grep the source file for the choice
        literal. This catches accidental removal during refactors.
        """
        src_path = os.path.join(SCRIPT_DIR, "codelens.py")
        with open(src_path, encoding="utf-8") as fh:
            src = fh.read()
        # 'graphml' must appear in the subparser default, global default,
        # and the 3 pre-parse recognition branches (5 occurrences total in
        # codelens.py). Match the bare word so both "graphml" and 'graphml'
        # forms are counted.
        occurrences = src.count("graphml")
        self.assertGreaterEqual(occurrences, 5,
                                 f"codelens.py must list 'graphml' in 5 places (format choices + pre-parse); found {occurrences}")


# ─── 2. Trace extraction ─────────────────────────────────────


class TestTraceExtraction(unittest.TestCase):
    """trace command: build graph from chains.up + chains.down."""

    def test_empty_chains_produces_just_symbol_node(self):
        data = {"status": "ok", "symbol": "main", "chains": {"up": [], "down": []}}
        out = format_graphml(data, "trace", "/tmp")
        nodes, edges, _keys = _counts(out)
        self.assertEqual(nodes, 1)
        self.assertEqual(edges, 0)

    def test_up_chain_builds_caller_edges(self):
        data = {
            "status": "ok",
            "symbol": "main",
            "chains": {
                "up": [
                    {"depth": 0, "direction": "caller", "node_id": "main",
                     "fn": "main", "file": "app.py", "line": 10, "path": "main"},
                    {"depth": 1, "direction": "caller", "node_id": "app.py:5:run",
                     "fn": "run", "file": "app.py", "line": 5, "path": "main → run"},
                ],
                "down": [],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].get("source"), "main")
        self.assertEqual(edges[0].get("target"), "app.py:5:run")

    def test_down_chain_builds_callee_edges(self):
        data = {
            "status": "ok", "symbol": "main",
            "chains": {
                "up": [],
                "down": [
                    {"depth": 0, "direction": "callee", "node_id": "main",
                     "fn": "main", "file": "app.py", "line": 10, "path": "main"},
                    {"depth": 1, "direction": "callee", "node_id": "app.py:20:helper",
                     "fn": "helper", "file": "app.py", "line": 20, "path": "main → helper"},
                ],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].get("source"), "main")
        self.assertEqual(edges[0].get("target"), "app.py:20:helper")

    def test_unresolved_node_becomes_external_placeholder(self):
        data = {
            "status": "ok", "symbol": "main",
            "chains": {
                "up": [
                    {"depth": 0, "direction": "caller", "node_id": "main",
                     "fn": "main", "file": "app.py", "line": 10, "path": "main"},
                    {"depth": 1, "direction": "caller", "node_id": "unresolved",
                     "fn": "external_lib", "resolved": False,
                     "path": "main → external_lib(unresolved)"},
                ],
                "down": [],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        # main + external:external_lib
        self.assertEqual(len(nodes), 2)
        ids = {n.get("id") for n in nodes}
        self.assertIn("external:external_lib", ids)

    def test_direction_attribute_attached_to_edges(self):
        data = {
            "status": "ok", "symbol": "main",
            "chains": {
                "up": [
                    {"depth": 0, "node_id": "main", "fn": "main"},
                    {"depth": 1, "node_id": "a", "fn": "a"},
                ],
                "down": [
                    {"depth": 0, "node_id": "main", "fn": "main"},
                    {"depth": 1, "node_id": "b", "fn": "b"},
                ],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        for edge in root.findall(".//g:edge", NS):
            dir_el = edge.find('g:data[@key="e1"]', NS)
            self.assertIsNotNone(dir_el, "edge missing direction data")
            self.assertIn(dir_el.text, ("up", "down"))


# ─── 3. Impact extraction ────────────────────────────────────


class TestImpactExtraction(unittest.TestCase):
    """impact command: build graph from affected.direct + affected.indirect."""

    def test_root_symbol_always_present(self):
        data = {"status": "ok", "symbol": "my_func", "affected": {
            "direct": [], "indirect": [], "files": [], "tests": []
        }}
        out = format_graphml(data, "impact", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].get("id"), "root:my_func")

    def test_direct_and_indirect_edges(self):
        data = {
            "status": "ok", "symbol": "my_func",
            "affected": {
                "direct": [
                    {"type": "function", "name": "caller1", "file": "a.py", "line": 5,
                     "relation": "calls my_func", "domain": "backend"},
                ],
                "indirect": [
                    {"type": "function", "name": "caller2", "file": "b.py", "line": 10,
                     "relation": "calls caller1", "domain": "backend"},
                ],
                "files": [], "tests": [],
            },
        }
        out = format_graphml(data, "impact", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(nodes), 3)  # root + direct + indirect
        self.assertEqual(len(edges), 2)
        # All edges originate at root
        for e in edges:
            self.assertEqual(e.get("source"), "root:my_func")
        # Kinds: one direct, one indirect
        kinds = []
        for e in edges:
            kind_el = e.find('g:data[@key="e0"]', NS)
            kinds.append(kind_el.text if kind_el is not None else None)
        self.assertIn("direct", kinds)
        self.assertIn("indirect", kinds)


# ─── 4. Circular extraction ──────────────────────────────────


class TestCircularExtraction(unittest.TestCase):
    """circular command: build graph from cycles (function/import/css)."""

    def test_recursion_renders_as_self_loop(self):
        data = {
            "status": "ok", "total_cycles": 1,
            "cycles": {
                "function_calls": [
                    {"type": "recursion", "chain": [
                        {"id": "a.py:1:foo", "fn": "foo", "file": "a.py", "line": 1},
                    ], "cycle": "foo → foo", "length": 1, "severity": "info"},
                ],
                "import_chains": [], "css_imports": [],
            },
        }
        out = format_graphml(data, "circular", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].get("source"), edges[0].get("target"))

    def test_explicit_closing_node_no_self_loop(self):
        """Chain [foo, bar, foo] should produce 2 edges, not 3 (no spurious self-loop)."""
        data = {
            "status": "ok", "total_cycles": 1,
            "cycles": {
                "function_calls": [
                    {"type": "function_call_cycle", "chain": [
                        {"id": "a.py:1:foo", "fn": "foo", "file": "a.py", "line": 1},
                        {"id": "b.py:2:bar", "fn": "bar", "file": "b.py", "line": 2},
                        {"id": "a.py:1:foo", "fn": "foo", "file": "a.py", "line": 1},
                    ], "cycle": "foo → bar → foo", "length": 2, "severity": "warning"},
                ],
                "import_chains": [], "css_imports": [],
            },
        }
        out = format_graphml(data, "circular", "/tmp")
        root = _parse(out)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(edges), 2)
        # No self-loops
        for e in edges:
            self.assertNotEqual(e.get("source"), e.get("target"))

    def test_chain_without_explicit_close_adds_wraparound(self):
        """Chain [foo, bar] should produce 2 edges (chain + closing wrap-around)."""
        data = {
            "status": "ok", "total_cycles": 1,
            "cycles": {
                "function_calls": [
                    {"type": "function_call_cycle", "chain": [
                        {"id": "a.py:1:foo", "fn": "foo", "file": "a.py", "line": 1},
                        {"id": "b.py:2:bar", "fn": "bar", "file": "b.py", "line": 2},
                    ], "cycle": "foo → bar → foo", "length": 2, "severity": "warning"},
                ],
                "import_chains": [], "css_imports": [],
            },
        }
        out = format_graphml(data, "circular", "/tmp")
        root = _parse(out)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(edges), 2)
        # The wrap-around edge must be present
        sources_targets = {(e.get("source"), e.get("target")) for e in edges}
        self.assertIn(("a.py:1:foo", "b.py:2:bar"), sources_targets)
        self.assertIn(("b.py:2:bar", "a.py:1:foo"), sources_targets)

    def test_cycle_id_is_stable_and_unique_per_cycle(self):
        data = {
            "status": "ok", "total_cycles": 2,
            "cycles": {
                "function_calls": [
                    {"type": "function_call_cycle", "chain": [
                        {"id": "a:1:foo", "fn": "foo"}, {"id": "a:1:foo", "fn": "foo"}],
                     "cycle": "foo → foo", "length": 1, "severity": "info"},
                    {"type": "function_call_cycle", "chain": [
                        {"id": "b:1:bar", "fn": "bar"}, {"id": "b:1:bar", "fn": "bar"}],
                     "cycle": "bar → bar", "length": 1, "severity": "info"},
                ],
                "import_chains": [], "css_imports": [],
            },
        }
        out = format_graphml(data, "circular", "/tmp")
        root = _parse(out)
        cycle_ids = set()
        for e in root.findall(".//g:edge", NS):
            cyc_el = e.find('g:data[@key="e2"]', NS)
            self.assertIsNotNone(cyc_el, "edge missing cycle_id")
            cycle_ids.add(cyc_el.text)
        self.assertEqual(len(cycle_ids), 2)

    def test_multiple_cycle_categories(self):
        data = {
            "status": "ok", "total_cycles": 2,
            "cycles": {
                "function_calls": [
                    {"type": "function_call_cycle", "chain": [
                        {"id": "a:1:foo", "fn": "foo"}, {"id": "b:1:bar", "fn": "bar"},
                        {"id": "a:1:foo", "fn": "foo"}],
                     "cycle": "foo → bar → foo", "length": 2, "severity": "warning"},
                ],
                "import_chains": [
                    {"type": "import_cycle", "chain": [
                        {"id": "mod_a", "fn": "mod_a"}, {"id": "mod_b", "fn": "mod_b"},
                        {"id": "mod_a", "fn": "mod_a"}],
                     "cycle": "mod_a → mod_b → mod_a", "length": 2, "severity": "warning"},
                ],
                "css_imports": [],
            },
        }
        out = format_graphml(data, "circular", "/tmp")
        root = _parse(out)
        cats = set()
        for e in root.findall(".//g:edge", NS):
            cat_el = e.find('g:data[@key="e4"]', NS)
            if cat_el is not None:
                cats.add(cat_el.text)
        self.assertEqual(cats, {"function_calls", "import_chains"})


# ─── 5. Scan extraction ──────────────────────────────────────


class TestScanExtraction(unittest.TestCase):
    """scan command: read full graph from SQLite graph_nodes/graph_edges."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="codelens_graphml_test_")
        db_dir = os.path.join(self.tmpdir, ".codelens")
        os.makedirs(db_dir)
        self.db_path = os.path.join(db_dir, "codelens.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE graph_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL UNIQUE,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                file TEXT,
                line INTEGER,
                extra_json TEXT
            );
            CREATE TABLE graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT,
                edge_type TEXT NOT NULL
            );
        """)
        conn.executemany(
            "INSERT INTO graph_nodes (node_id, node_type, name, file, line) VALUES (?, ?, ?, ?, ?)",
            [
                ("app.py:1:main", "function", "main", "app.py", 1),
                ("app.py:5:helper", "function", "helper", "app.py", 5),
                ("lib.py:10:util", "function", "util", "lib.py", 10),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges (source_id, target_id, edge_type) VALUES (?, ?, ?)",
            [
                ("app.py:1:main", "app.py:5:helper", "CALLS"),
                ("app.py:5:helper", "lib.py:10:util", "CALLS"),
                ("app.py:1:main", None, "CALLS"),  # should be skipped
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_graph_extracted_from_sqlite(self):
        data = {"status": "ok", "stats": {"nodes": 3, "edges": 2}}
        out = format_graphml(data, "scan", self.tmpdir)
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        edges = root.findall(".//g:edge", NS)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(len(edges), 2)  # NULL target edge skipped
        # Verify edge kind is the SQLite edge_type
        for e in edges:
            kind_el = e.find('g:data[@key="e0"]', NS)
            self.assertEqual(kind_el.text, "CALLS")

    def test_missing_db_returns_placeholder(self):
        data = {"status": "ok"}
        out = format_graphml(data, "scan", "/nonexistent/path")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)
        warn_el = nodes[0].find('g:data[@key="d4"]', NS)
        self.assertIsNotNone(warn_el)
        self.assertIn("not found", warn_el.text.lower())

    def test_empty_graph_tables_return_placeholder(self):
        # Wipe the tables but keep them existing
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM graph_edges")
        conn.execute("DELETE FROM graph_nodes")
        conn.commit()
        conn.close()
        data = {"status": "ok"}
        out = format_graphml(data, "scan", self.tmpdir)
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)
        warn_el = nodes[0].find('g:data[@key="d4"]', NS)
        self.assertIsNotNone(warn_el)
        self.assertIn("no nodes", warn_el.text.lower())


# ─── 6. Placeholder fallback ─────────────────────────────────


class TestPlaceholderFallback(unittest.TestCase):
    """Non-graph commands get a single-node placeholder graph."""

    def test_init_returns_placeholder(self):
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)
        type_el = nodes[0].find('g:data[@key="d1"]', NS)
        self.assertEqual(type_el.text, "placeholder")
        warn_el = nodes[0].find('g:data[@key="d4"]', NS)
        self.assertIsNotNone(warn_el)
        self.assertIn("does not produce graph data", warn_el.text)

    def test_unknown_command_returns_placeholder(self):
        out = format_graphml({"status": "ok"}, "totally_made_up_command", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)

    def test_non_dict_input_returns_placeholder(self):
        out = format_graphml(["not", "a", "dict"], "scan", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        self.assertEqual(len(nodes), 1)

    def test_status_carried_into_placeholder(self):
        out = format_graphml({"status": "error", "error": "oops"}, "init", "/tmp")
        root = _parse(out)
        nodes = root.findall(".//g:node", NS)
        status_el = nodes[0].find('g:data[@key="d5"]', NS)
        self.assertIsNotNone(status_el)
        self.assertEqual(status_el.text, "error")


# ─── 7. GraphML XML validity ─────────────────────────────────


class TestGraphMLValidity(unittest.TestCase):
    """The output must be valid GraphML 1.0 XML."""

    def test_root_element_is_graphml_in_namespace(self):
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        root = _parse(out)
        self.assertEqual(root.tag, f"{{{GRAPHML_NS}}}graphml")

    def test_graph_element_has_directed_default(self):
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        root = _parse(out)
        graph = root.find("g:graph", NS)
        self.assertIsNotNone(graph)
        self.assertEqual(graph.get("edgedefault"), "directed")

    def test_key_declarations_present_for_node_and_edge(self):
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        root = _parse(out)
        node_keys = root.findall('./g:key[@for="node"]', NS)
        edge_keys = root.findall('./g:key[@for="edge"]', NS)
        self.assertGreater(len(node_keys), 0)
        self.assertGreater(len(edge_keys), 0)

    def test_node_ids_unique(self):
        """All <node> elements in a single document must have unique IDs."""
        data = {
            "status": "ok", "symbol": "x",
            "chains": {
                "up": [
                    {"node_id": "x", "fn": "x"},
                    {"node_id": "y", "fn": "y"},
                ],
                "down": [
                    {"node_id": "x", "fn": "x"},
                    {"node_id": "z", "fn": "z"},
                ],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        ids = [n.get("id") for n in root.findall(".//g:node", NS)]
        self.assertEqual(len(ids), len(set(ids)), f"node IDs not unique: {ids}")

    def test_edge_references_resolve_to_existing_nodes(self):
        """Every edge source/target must match a node id."""
        data = {
            "status": "ok", "symbol": "x",
            "chains": {
                "up": [
                    {"node_id": "x", "fn": "x"},
                    {"node_id": "y", "fn": "y"},
                ],
                "down": [],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        root = _parse(out)
        ids = {n.get("id") for n in root.findall(".//g:node", NS)}
        for e in root.findall(".//g:edge", NS):
            self.assertIn(e.get("source"), ids, f"edge source {e.get('source')} not in nodes")
            self.assertIn(e.get("target"), ids, f"edge target {e.get('target')} not in nodes")

    def test_data_keys_reference_declared_key_ids(self):
        """Every <data key="..."> must reference a <key id="..."> declared at top."""
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        root = _parse(out)
        declared = {k.get("id") for k in root.findall("./g:key", NS)}
        for data in root.findall(".//g:data", NS):
            self.assertIn(data.get("key"), declared,
                          f"data key '{data.get('key')}' not declared in <key> elements")

    def test_xml_declaration_present(self):
        out = format_graphml({"status": "ok"}, "init", "/tmp")
        self.assertTrue(out.startswith("<?xml"), "missing XML declaration")

    def test_boolean_serialized_as_true_false(self):
        """GraphML spec mandates 'true'/'false' (not 'True'/'False')."""
        # Use trace with an unresolved external node — that sets resolved=False
        data = {
            "status": "ok", "symbol": "x",
            "chains": {
                "up": [
                    {"node_id": "x", "fn": "x"},
                    {"node_id": "unresolved", "fn": "ext"},
                ],
                "down": [],
            },
        }
        out = format_graphml(data, "trace", "/tmp")
        # Find the resolved data element
        root = _parse(out)
        resolved_values = []
        for d in root.findall(".//g:data", NS):
            if d.get("key") == "d12":  # d12 = resolved (boolean)
                resolved_values.append(d.text)
        self.assertTrue(all(v in ("true", "false") for v in resolved_values),
                        f"boolean values not 'true'/'false': {resolved_values}")

    def test_never_raises_on_any_input(self):
        """format_graphml must never raise — always return valid XML."""
        weird_inputs = [
            None, "", [], [1, 2, 3], {"status": "ok"},
            {"chains": "not_a_dict"}, {"chains": {"up": "not_a_list"}},
            {"affected": "not_a_dict"},
            {"cycles": "not_a_dict"}, {"cycles": {"function_calls": "not_a_list"}},
            {"cycles": {"function_calls": [{"chain": "not_a_list"}]}},
        ]
        for inp in weird_inputs:
            try:
                out = format_graphml(inp, "scan", "/tmp")
                _parse(out)  # must parse
            except Exception as exc:
                self.fail(f"format_graphml raised on input {inp!r}: {exc}")


# ─── 8. Direct extractor unit tests ──────────────────────────


class TestExtractorsDirectly(unittest.TestCase):
    """Call internal extractors directly to verify (nodes, edges) tuples."""

    def test_extract_default_graph(self):
        nodes, edges = _extract_default_graph({"status": "ok"}, "init")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(edges, [])
        self.assertEqual(nodes[0]["type"], "placeholder")

    def test_extract_trace_graph_returns_tuple(self):
        data = {"status": "ok", "symbol": "x",
                "chains": {"up": [{"node_id": "x", "fn": "x"}], "down": []}}
        nodes, edges = _extract_trace_graph(data, "/tmp")
        self.assertIsInstance(nodes, list)
        self.assertIsInstance(edges, list)
        self.assertEqual(len(nodes), 1)

    def test_extract_impact_graph_returns_tuple(self):
        data = {"status": "ok", "symbol": "x", "affected": {
            "direct": [{"name": "y", "file": "a", "line": 1, "type": "function"}],
            "indirect": [], "files": [], "tests": [],
        }}
        nodes, edges = _extract_impact_graph(data, "/tmp")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)

    def test_extract_circular_graph_returns_tuple(self):
        data = {"status": "ok", "cycles": {
            "function_calls": [{"chain": [{"id": "a", "fn": "a"}]}],
            "import_chains": [], "css_imports": [],
        }}
        nodes, edges = _extract_circular_graph(data, "/tmp")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(len(edges), 1)  # self-loop

    def test_serialize_graphml_roundtrips(self):
        nodes = [{"id": "n1", "name": "node1", "type": "function"}]
        edges = [{"source": "n1", "target": "n1", "kind": "cycle"}]
        out = _serialize_graphml(nodes, edges)
        root = _parse(out)
        self.assertEqual(len(root.findall(".//g:node", NS)), 1)
        self.assertEqual(len(root.findall(".//g:edge", NS)), 1)


if __name__ == "__main__":
    unittest.main()

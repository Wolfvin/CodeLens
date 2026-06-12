"""
Tests for the Edge Resolver — cross-file function call resolution.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from edge_resolver import resolve_edges, get_callers, get_callees


class TestEdgeResolver:
    """Test cross-file edge resolution."""

    def test_resolve_simple_edges(self):
        nodes = [
            {"id": "a.ts:1", "fn": "hello", "file": "a.ts", "line": 1, "ref_count": 0, "status": "dead"},
            {"id": "b.ts:1", "fn": "world", "file": "b.ts", "line": 1, "ref_count": 0, "status": "dead"},
        ]
        edges = [
            {"from": "a.ts:1", "to_fn": "world"},
        ]
        resolved_nodes, resolved_edges = resolve_edges(nodes, edges)
        assert len(resolved_edges) == 1
        assert resolved_edges[0]["to"] == "b.ts:1"

    def test_resolve_unresolved_edge(self):
        nodes = [
            {"id": "a.ts:1", "fn": "hello", "file": "a.ts", "line": 1, "ref_count": 0, "status": "dead"},
        ]
        edges = [
            {"from": "a.ts:1", "to_fn": "external_fn"},
        ]
        resolved_nodes, resolved_edges = resolve_edges(nodes, edges)
        # External function should remain as unresolved
        assert len(resolved_edges) == 1
        assert resolved_edges[0].get("resolved") is False

    def test_get_callers(self):
        edges = [
            {"from": "a.ts:1", "to": "b.ts:1"},
            {"from": "c.ts:1", "to": "b.ts:1"},
        ]
        callers = get_callers("b.ts:1", edges)
        assert len(callers) == 2

    def test_get_callees(self):
        edges = [
            {"from": "a.ts:1", "to": "b.ts:1"},
            {"from": "a.ts:1", "to": "c.ts:1"},
        ]
        nodes = [
            {"id": "b.ts:1", "fn": "world", "status": "active"},
            {"id": "c.ts:1", "fn": "foo", "status": "active"},
        ]
        callees = get_callees("a.ts:1", edges, nodes)
        assert len(callees) == 2

    def test_empty_edges(self):
        nodes = [
            {"id": "a.ts:1", "fn": "hello", "file": "a.ts", "line": 1, "ref_count": 0, "status": "dead"},
        ]
        resolved_nodes, resolved_edges = resolve_edges(nodes, [])
        assert len(resolved_edges) == 0
        assert len(resolved_nodes) == 1

    def test_ref_count_computation(self):
        nodes = [
            {"id": "a.ts:1", "fn": "hello", "file": "a.ts", "line": 1, "ref_count": 0, "status": "dead"},
            {"id": "b.ts:1", "fn": "world", "file": "b.ts", "line": 1, "ref_count": 0, "status": "dead"},
        ]
        edges = [
            {"from": "a.ts:1", "to_fn": "world"},
        ]
        resolved_nodes, resolved_edges = resolve_edges(nodes, edges)
        # world should have ref_count = 1 after resolution
        for node in resolved_nodes:
            if node["fn"] == "world":
                assert node["ref_count"] >= 1

"""
Tests for the Registry module — building, loading, saving registries.
"""

import os
import sys
import json
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, save_frontend_registry,
    load_backend_registry, save_backend_registry,
    build_frontend_registry, compute_frontend_status,
    compute_backend_status
)


class TestConfig:
    """Test config loading and saving."""

    def test_default_config(self):
        with tempfile.TemporaryDirectory() as ws:
            config = load_config(ws)
            assert "frontend_paths" in config
            assert "backend_paths" in config
            assert "ignore" in config
            assert isinstance(config["frontend_paths"], list)
            assert isinstance(config["backend_paths"], list)

    def test_save_and_load_config(self):
        with tempfile.TemporaryDirectory() as ws:
            config = {
                "frontend_paths": ["src/app/"],
                "backend_paths": ["src/server/"],
                "ignore": ["node_modules/"],
                "watch": True
            }
            ensure_codelens_dir(ws)
            save_config(ws, config)
            loaded = load_config(ws)
            assert loaded["frontend_paths"] == ["src/app/"]
            assert loaded["backend_paths"] == ["src/server/"]

    def test_config_merge_with_defaults(self):
        with tempfile.TemporaryDirectory() as ws:
            ensure_codelens_dir(ws)
            save_config(ws, {"frontend_paths": ["custom/"]})
            loaded = load_config(ws)
            assert loaded["frontend_paths"] == ["custom/"]
            # Defaults should be present for keys not overridden
            assert "backend_paths" in loaded


class TestFrontendRegistry:
    """Test frontend registry building and status computation."""

    def test_compute_frontend_status_active(self):
        status = compute_frontend_status(
            "btn-primary", "class",
            html_refs=[{"path": "index.html"}],
            css_refs=[{"path": "style.css", "line": 10, "flag": None}],
            js_refs=[{"path": "app.js", "line": 55, "flag": None}]
        )
        assert status == "active"

    def test_compute_frontend_status_dead(self):
        status = compute_frontend_status(
            "old-header", "class",
            html_refs=[{"path": "index.html"}],
            css_refs=[],
            js_refs=[]
        )
        assert status == "dead"

    def test_compute_frontend_status_collision(self):
        status = compute_frontend_status(
            "duplicate-id", "id",
            html_refs=[{"path": "page1.html"}, {"path": "page2.html"}],
            css_refs=[{"path": "style.css", "line": 10, "flag": None}],
            js_refs=[]
        )
        assert status == "collision"

    def test_compute_frontend_status_duplicate_ref(self):
        status = compute_frontend_status(
            "shared-btn", "class",
            html_refs=[],
            css_refs=[{"path": "style.css", "line": 10, "flag": None}],
            js_refs=[
                {"path": "app.js", "line": 55, "flag": None},
                {"path": "utils.js", "line": 12, "flag": None}
            ]
        )
        assert status == "duplicate_ref"

    def test_build_frontend_registry(self):
        with tempfile.TemporaryDirectory() as ws:
            html_data = [{
                "path": "index.html",
                "classes": [{"name": "btn", "line": 1, "flag": None}],
                "ids": [{"name": "main", "line": 2, "flag": None}]
            }]
            css_data = [{
                "path": "style.css",
                "classes": [{"name": "btn", "line": 10, "flag": None}],
                "ids": []
            }]
            js_data = [{
                "path": "app.js",
                "classes": [],
                "ids": [{"name": "main", "line": 55, "flag": None}]
            }]

            registry = build_frontend_registry(ws, html_data, css_data, js_data)
            assert len(registry["classes"]) == 1
            assert registry["classes"][0]["name"] == "btn"
            assert len(registry["ids"]) == 1
            assert registry["ids"][0]["name"] == "main"

    def test_save_and_load_frontend_registry(self):
        with tempfile.TemporaryDirectory() as ws:
            ensure_codelens_dir(ws)
            data = {
                "classes": [{"name": "btn", "ref_count": 2, "status": "active", "css": [], "js": []}],
                "ids": []
            }
            save_frontend_registry(ws, data)
            loaded = load_frontend_registry(ws)
            assert loaded["classes"][0]["name"] == "btn"


class TestBackendRegistry:
    """Test backend registry building and status computation."""

    def test_compute_backend_status_dead(self):
        assert compute_backend_status(0) == "dead"

    def test_compute_backend_status_active(self):
        assert compute_backend_status(1) == "active"
        assert compute_backend_status(5) == "active"

    def test_save_and_load_backend_registry(self):
        with tempfile.TemporaryDirectory() as ws:
            ensure_codelens_dir(ws)
            data = {
                "nodes": [{"id": "test:1", "fn": "hello", "ref_count": 0, "status": "dead"}],
                "edges": []
            }
            save_backend_registry(ws, data)
            loaded = load_backend_registry(ws)
            assert loaded["nodes"][0]["fn"] == "hello"

    def test_empty_registry_load(self):
        with tempfile.TemporaryDirectory() as ws:
            loaded = load_frontend_registry(ws)
            assert loaded["classes"] == []
            assert loaded["ids"] == []

            loaded = load_backend_registry(ws)
            assert loaded["nodes"] == []
            assert loaded["edges"] == []

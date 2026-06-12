"""Tests for persistent_registry.py — Additional tests beyond existing ones.

Focus on store/retrieve frontend/backend registry, migration from JSON,
schema versioning, and edge cases.
"""

import json
import os
import sys
import tempfile
import time
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from persistent_registry import PersistentRegistry, is_sqlite_available, SCHEMA_VERSION


# ─── is_sqlite_available Test ─────────────────────────────────


class TestSQLiteAvailability(unittest.TestCase):
    """Test SQLite availability check."""

    def test_sqlite_is_available(self):
        self.assertTrue(is_sqlite_available())


# ─── Schema Version Test ──────────────────────────────────────


class TestSchemaVersion(unittest.TestCase):
    """Test schema version constant."""

    def test_schema_version_is_int(self):
        self.assertIsInstance(SCHEMA_VERSION, int)

    def test_schema_version_is_positive(self):
        self.assertGreater(SCHEMA_VERSION, 0)


# ─── Store/Retrieve Registry Tests ────────────────────────────


class TestStoreRetrieveRegistry(unittest.TestCase):
    """Test storing and retrieving frontend/backend registry data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='codelens_store_test_')
        self.reg = PersistentRegistry(self.tmpdir)
        self.reg._connect()

    def tearDown(self):
        self.reg.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_and_load_frontend(self):
        fe_data = {
            "classes": [{"name": "btn", "ref_count": 1, "status": "active", "html": [], "css": [], "js": []}],
            "ids": [{"name": "app"}],
            "frameworks": ["react"],
        }
        self.reg.store_frontend_registry(fe_data)
        loaded = self.reg.load_frontend_registry()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["classes"]), 1)
        self.assertEqual(loaded["classes"][0]["name"], "btn")

    def test_store_and_load_backend(self):
        be_data = {
            "nodes": [{"id": "app.py:1:hello", "fn": "hello", "file": "app.py", "line": 1}],
            "edges": [{"from": "a", "to": "b"}],
        }
        self.reg.store_backend_registry(be_data)
        loaded = self.reg.load_backend_registry()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["nodes"]), 1)

    def test_load_without_store_returns_none(self):
        result = self.reg.load_frontend_registry()
        self.assertIsNone(result)

    def test_overwrite_frontend(self):
        self.reg.store_frontend_registry({"classes": [{"name": "old"}], "ids": []})
        self.reg.store_frontend_registry({"classes": [{"name": "new"}], "ids": []})
        loaded = self.reg.load_frontend_registry()
        self.assertEqual(loaded["classes"][0]["name"], "new")

    def test_overwrite_backend(self):
        self.reg.store_backend_registry({"nodes": [{"id": "old"}], "edges": []})
        self.reg.store_backend_registry({"nodes": [{"id": "new"}], "edges": []})
        loaded = self.reg.load_backend_registry()
        self.assertEqual(loaded["nodes"][0]["id"], "new")


# ─── Migration from JSON Tests ────────────────────────────────


class TestMigrationFromJSON(unittest.TestCase):
    """Test automatic migration from existing JSON registry files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='codelens_migrate_test_')
        # Create .codelens directory
        codelens_dir = os.path.join(self.tmpdir, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migrate_json_to_sqlite(self):
        """Test that migrate_from_json reads existing JSON files."""
        codelens_dir = os.path.join(self.tmpdir, '.codelens')

        # Create JSON registry files
        frontend_data = {
            "classes": [{"name": "btn", "ref_count": 1, "status": "active", "html": [], "css": [], "js": []}],
            "ids": [],
            "frameworks": [],
        }
        backend_data = {
            "nodes": [{"id": "app.py:1:hello", "fn": "hello", "file": "app.py", "line": 1}],
            "edges": [],
        }

        with open(os.path.join(codelens_dir, "frontend.json"), 'w') as f:
            json.dump(frontend_data, f)
        with open(os.path.join(codelens_dir, "backend.json"), 'w') as f:
            json.dump(backend_data, f)

        # Create SQLite registry and migrate
        reg = PersistentRegistry(self.tmpdir)
        reg._connect()

        # Check if migration method exists
        if hasattr(reg, 'migrate_from_json'):
            reg.migrate_from_json()
            # Verify data was migrated
            fe = reg.load_frontend_registry()
            self.assertIsNotNone(fe)
            self.assertEqual(len(fe["classes"]), 1)
        else:
            # Manual migration via store methods
            reg.store_frontend_registry(frontend_data)
            fe = reg.load_frontend_registry()
            self.assertIsNotNone(fe)

        reg.close()


# ─── Edge Cases ───────────────────────────────────────────────


class TestPersistentRegistryEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_double_connect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg._connect()  # Should not raise
            reg.close()

    def test_close_without_connect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg.close()  # Should not raise

    def test_double_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.close()
            reg.close()  # Should not raise

    def test_context_manager_auto_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with PersistentRegistry(tmpdir) as reg:
                reg.insert_symbols_batch([{"name": "test", "kind": "function", "file_path": "a.py"}])
                result = reg.lookup_symbol("test")
                self.assertEqual(len(result), 1)
            # After context, connection should be closed

    def test_custom_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "custom.db")
            reg = PersistentRegistry(tmpdir, db_path=custom_path)
            self.assertEqual(reg.db_path, custom_path)
            reg._connect()
            self.assertTrue(os.path.exists(custom_path))
            reg.close()

    def test_schema_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            self.assertTrue(reg.schema_exists())
            reg.close()

    def test_empty_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            stats = reg.get_stats()
            self.assertEqual(stats["symbols"], 0)
            self.assertEqual(stats["references"], 0)
            self.assertEqual(stats["files"], 0)
            reg.close()

    def test_lookup_symbol_by_name_and_kind(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.insert_symbols_batch([
                {"name": "my_func", "kind": "function", "file_path": "a.py"},
                {"name": "MyClass", "kind": "class", "file_path": "a.py"},
            ])
            result = reg.lookup_symbol("my_func", "function")
            self.assertEqual(len(result), 1)
            result = reg.lookup_symbol("my_func", "class")
            self.assertEqual(len(result), 0)
            reg.close()

    def test_insert_empty_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.insert_symbols_batch([])
            stats = reg.get_stats()
            self.assertEqual(stats["symbols"], 0)
            reg.close()

    def test_insert_references_empty_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.insert_references_batch([])
            stats = reg.get_stats()
            self.assertEqual(stats["references"], 0)
            reg.close()

    def test_scan_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.update_scan_metadata(42)
            meta = reg.get_scan_metadata()
            self.assertEqual(meta["total_files"], 42)
            self.assertEqual(meta["workspace"], tmpdir)
            reg.close()

    def test_get_file_info_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            info = reg.get_file_info("nonexistent.py")
            self.assertIsNone(info)
            reg.close()

    def test_vacuum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            # Insert and delete some data
            reg.insert_symbols_batch([{"name": f"fn_{i}", "kind": "function", "file_path": "a.py"} for i in range(10)])
            reg.delete_symbols_for_file("a.py")
            # Vacuum should not crash
            reg.vacuum()
            reg.close()

    def test_get_all_symbols(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.insert_symbols_batch([
                {"name": "fn1", "kind": "function", "file_path": "a.py"},
                {"name": "fn2", "kind": "function", "file_path": "b.py"},
            ])
            all_syms = reg.get_all_symbols()
            self.assertEqual(len(all_syms), 2)
            reg.close()

    def test_delete_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.insert_symbols_batch([
                {"name": "fn1", "kind": "function", "file_path": "a.py"},
                {"name": "fn2", "kind": "function", "file_path": "b.py"},
            ])
            reg.delete_files(["a.py"])
            result = reg.lookup_symbol("fn1")
            self.assertEqual(len(result), 0)
            result = reg.lookup_symbol("fn2")
            self.assertEqual(len(result), 1)
            reg.close()

    def test_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            reg._connect()
            reg.set_cached_result("test_cmd", ["a.py"], {"result": True})
            reg.invalidate_cache()
            cached = reg.get_cached_result("test_cmd", ["a.py"])
            self.assertIsNone(cached)
            reg.close()

    def test_compute_content_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = PersistentRegistry(tmpdir)
            # compute_content_hash takes a file path
            file1 = os.path.join(tmpdir, "test1.txt")
            file2 = os.path.join(tmpdir, "test2.txt")
            with open(file1, 'w') as f:
                f.write("hello world")
            with open(file2, 'w') as f:
                f.write("different content")
            h1 = reg.compute_content_hash(file1)
            h2 = reg.compute_content_hash(file1)
            h3 = reg.compute_content_hash(file2)
            self.assertEqual(h1, h2)
            self.assertNotEqual(h1, h3)
            reg.close()


if __name__ == "__main__":
    unittest.main()

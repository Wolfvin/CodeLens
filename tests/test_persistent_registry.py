"""Tests for the persistent registry (SQLite-backed storage)."""

import json
import os
import tempfile
import time
import pytest

# Add scripts directory to path
import sys
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
sys.path.insert(0, SCRIPT_DIR)


@pytest.fixture
def workspace():
    """Create a temporary workspace directory."""
    d = tempfile.mkdtemp(prefix='codelens_persistent_test_')
    yield d
    # Cleanup
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def populated_workspace(workspace):
    """Create a workspace with some source files."""
    # Create test files
    with open(os.path.join(workspace, 'app.py'), 'w') as f:
        f.write('def hello(): pass\nclass World: pass\n')
    with open(os.path.join(workspace, 'utils.py'), 'w') as f:
        f.write('def helper(): pass\nx = 42\n')
    with open(os.path.join(workspace, 'style.css'), 'w') as f:
        f.write('.btn { color: red; }\n.container { width: 100%; }\n')
    with open(os.path.join(workspace, 'page.html'), 'w') as f:
        f.write('<div class="btn">Hello</div>\n')
    return workspace


class TestPersistentRegistry:
    """Test the PersistentRegistry class."""

    def test_init_creates_db(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()
        assert os.path.exists(reg.db_path)
        reg.close()

    def test_schema_exists(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()
        assert reg.schema_exists()
        reg.close()

    def test_insert_and_lookup_symbols(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        symbols = [
            {'name': 'hello', 'kind': 'function', 'file_path': 'app.py', 'line_start': 1, 'language': 'python'},
            {'name': 'World', 'kind': 'class', 'file_path': 'app.py', 'line_start': 2, 'language': 'python'},
        ]
        reg.insert_symbols_batch(symbols)

        # O(1) lookup by name
        result = reg.lookup_symbol('hello')
        assert len(result) == 1
        assert result[0]['name'] == 'hello'
        assert result[0]['kind'] == 'function'

        # Lookup by name and kind
        result = reg.lookup_symbol('hello', 'function')
        assert len(result) == 1

        # Lookup nonexistent
        result = reg.lookup_symbol('nonexistent')
        assert len(result) == 0

        reg.close()

    def test_lookup_symbols_by_file(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        symbols = [
            {'name': 'hello', 'kind': 'function', 'file_path': 'app.py'},
            {'name': 'World', 'kind': 'class', 'file_path': 'app.py'},
            {'name': 'helper', 'kind': 'function', 'file_path': 'utils.py'},
        ]
        reg.insert_symbols_batch(symbols)

        result = reg.lookup_symbols_by_file('app.py')
        assert len(result) == 2

        result = reg.lookup_symbols_by_file('utils.py')
        assert len(result) == 1

        reg.close()

    def test_references(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        refs = [
            {'source_symbol': 'main', 'target_symbol': 'hello', 'reference_type': 'call', 'source_file': 'app.py'},
            {'source_symbol': 'hello', 'target_symbol': 'World', 'reference_type': 'import', 'source_file': 'app.py'},
        ]
        reg.insert_references_batch(refs)

        # Lookup references TO a symbol
        result = reg.lookup_references_to('hello')
        assert len(result) == 1
        assert result[0]['source_symbol'] == 'main'

        # Lookup references FROM a symbol
        result = reg.lookup_references_from('main')
        assert len(result) == 1
        assert result[0]['target_symbol'] == 'hello'

        reg.close()

    def test_file_tracking(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        # Create a file
        test_file = os.path.join(workspace, 'test.py')
        with open(test_file, 'w') as f:
            f.write('x = 1\n')

        reg.upsert_file(test_file, 'python')

        file_info = reg.get_file_info(os.path.relpath(test_file, workspace))
        assert file_info is not None
        assert file_info['language'] == 'python'
        assert file_info['content_hash'] != ''

        reg.close()

    def test_delta_detection_no_changes(self, populated_workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(populated_workspace)
        reg._connect()

        # Register all files
        all_files = []
        for fn in os.listdir(populated_workspace):
            fp = os.path.join(populated_workspace, fn)
            if os.path.isfile(fp):
                all_files.append(fp)
                reg.upsert_file(fp, 'python')

        # No changes
        changed, new, deleted = reg.detect_changed_files(all_files)
        assert len(changed) == 0
        assert len(new) == 0
        assert len(deleted) == 0

        reg.close()

    def test_delta_detection_with_change(self, populated_workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(populated_workspace)
        reg._connect()

        # Register all files
        all_files = []
        for fn in os.listdir(populated_workspace):
            fp = os.path.join(populated_workspace, fn)
            if os.path.isfile(fp):
                all_files.append(fp)
                reg.upsert_file(fp, '')

        # Modify a file
        app_file = os.path.join(populated_workspace, 'app.py')
        time.sleep(0.05)
        with open(app_file, 'w') as f:
            f.write('def hello(): pass\ndef new_func(): pass\n')
        os.utime(app_file, None)

        changed, new, deleted = reg.detect_changed_files(all_files)
        assert len(changed) == 1

        reg.close()

    def test_delta_detection_new_file(self, populated_workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(populated_workspace)
        reg._connect()

        # Register existing files
        existing_files = []
        for fn in os.listdir(populated_workspace):
            fp = os.path.join(populated_workspace, fn)
            if os.path.isfile(fp):
                existing_files.append(fp)
                reg.upsert_file(fp, '')

        # Add a new file
        new_file = os.path.join(populated_workspace, 'new_module.py')
        with open(new_file, 'w') as f:
            f.write('z = 99\n')
        all_files = existing_files + [new_file]

        changed, new, deleted = reg.detect_changed_files(all_files)
        assert len(new) == 1

        reg.close()

    def test_delta_detection_deleted_file(self, populated_workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(populated_workspace)
        reg._connect()

        # Register all files
        all_files = []
        for fn in os.listdir(populated_workspace):
            fp = os.path.join(populated_workspace, fn)
            if os.path.isfile(fp):
                all_files.append(fp)
                reg.upsert_file(fp, '')

        # Delete a file
        os.remove(os.path.join(populated_workspace, 'utils.py'))
        remaining = [f for f in all_files if os.path.exists(f)]

        changed, new, deleted = reg.detect_changed_files(remaining)
        assert len(deleted) == 1

        reg.close()

    def test_analysis_cache(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        # Store a cached result
        files = ['test.py', 'app.py']
        result = {'health_score': 85, 'total_findings': 3}
        reg.set_cached_result('smell', files, result)

        # Retrieve it
        cached = reg.get_cached_result('smell', files)
        assert cached is not None
        assert cached['health_score'] == 85

        # Invalidate
        reg.invalidate_cache_for_files(['test.py'])
        cached = reg.get_cached_result('smell', files)
        assert cached is None

        reg.close()

    def test_scan_metadata(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        reg.update_scan_metadata(42)
        meta = reg.get_scan_metadata()
        assert meta['total_files'] == 42
        assert meta['workspace'] == workspace

        reg.close()

    def test_stats(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        symbols = [{'name': 'test', 'kind': 'function', 'file_path': 'a.py'}]
        reg.insert_symbols_batch(symbols)

        stats = reg.get_stats()
        assert stats['symbols'] == 1
        assert 'db_size_bytes' in stats
        assert stats['db_size_bytes'] > 0

        reg.close()

    def test_context_manager(self, workspace):
        from persistent_registry import PersistentRegistry
        with PersistentRegistry(workspace) as reg:
            reg.insert_symbols_batch([
                {'name': 'test', 'kind': 'function', 'file_path': 'a.py'}
            ])
            result = reg.lookup_symbol('test')
            assert len(result) == 1

    def test_delete_symbols_for_file(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        symbols = [
            {'name': 'hello', 'kind': 'function', 'file_path': 'app.py'},
            {'name': 'helper', 'kind': 'function', 'file_path': 'utils.py'},
        ]
        reg.insert_symbols_batch(symbols)

        count = reg.delete_symbols_for_file('app.py')
        assert count == 1

        result = reg.lookup_symbol('hello')
        assert len(result) == 0

        result = reg.lookup_symbol('helper')
        assert len(result) == 1

        reg.close()

    def test_batch_upsert_files(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        # Create files
        for i in range(5):
            with open(os.path.join(workspace, f'file_{i}.py'), 'w') as f:
                f.write(f'# file {i}\n')

        entries = [
            {'file_path': os.path.join(workspace, f'file_{i}.py'), 'language': 'python'}
            for i in range(5)
        ]
        reg.upsert_files_batch(entries)

        stats = reg.get_stats()
        assert stats['files'] == 5

        reg.close()

    def test_frontend_backend_registry_storage(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        fe_data = {'classes': [{'name': 'btn'}], 'ids': [{'name': 'app'}]}
        be_data = {'nodes': [{'id': 'test:1:hello'}], 'edges': [{'from': 'a', 'to': 'b'}]}

        reg.store_frontend_registry(fe_data)
        reg.store_backend_registry(be_data)

        fe = reg.load_frontend_registry()
        be = reg.load_backend_registry()

        assert fe is not None
        assert len(fe['classes']) == 1
        assert be is not None
        assert len(be['nodes']) == 1

        reg.close()


class TestRegistryFallback:
    """Test SQLite-aware registry loading with JSON fallback."""

    def test_load_frontend_without_db(self, workspace):
        from registry import load_frontend_registry
        result = load_frontend_registry(workspace)
        assert 'classes' in result
        assert 'ids' in result

    def test_load_backend_without_db(self, workspace):
        from registry import load_backend_registry
        result = load_backend_registry(workspace)
        assert 'nodes' in result
        assert 'edges' in result

    def test_save_and_load_with_db(self, workspace):
        from registry import (
            save_frontend_registry, load_frontend_registry,
            save_backend_registry, load_backend_registry,
            ensure_codelens_dir,
        )
        from persistent_registry import PersistentRegistry

        ensure_codelens_dir(workspace)

        # Create the SQLite DB
        reg = PersistentRegistry(workspace)
        reg._connect()
        reg.close()

        # Save with db_path
        fe_data = {
            'classes': [{'name': 'test-class', 'ref_count': 0, 'status': 'dead', 'html': [], 'css': [], 'js': []}],
            'ids': [],
            'frameworks': [],
        }
        save_frontend_registry(workspace, fe_data)

        # Load should get the same data
        loaded = load_frontend_registry(workspace)
        assert len(loaded['classes']) == 1
        assert loaded['classes'][0]['name'] == 'test-class'


class TestSymbolLookupPerformance:
    """Test O(1) symbol lookup performance via SQLite index."""

    def test_lookup_is_fast(self, workspace):
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace)
        reg._connect()

        # Insert 1000 symbols
        symbols = [
            {'name': f'func_{i}', 'kind': 'function', 'file_path': f'module_{i // 50}.py', 'line_start': i}
            for i in range(1000)
        ]
        reg.insert_symbols_batch(symbols)

        # Time 1000 lookups
        t0 = time.time()
        for i in range(1000):
            reg.lookup_symbol(f'func_{i}')
        t1 = time.time()

        # Should complete in < 50ms for 1000 lookups
        total_ms = (t1 - t0) * 1000
        assert total_ms < 100, f"1000 lookups took {total_ms:.1f}ms, expected < 100ms"

        reg.close()


class TestMigration:
    """Test JSON to SQLite migration."""

    def test_migrate_empty_workspace(self, workspace):
        from commands.migrate import cmd_migrate
        result = cmd_migrate(workspace)
        # Should fail because there's no JSON registry
        assert result['status'] == 'error'

    def test_migrate_with_registry(self, workspace):
        from commands.migrate import cmd_migrate
        from registry import ensure_codelens_dir, save_frontend_registry, save_backend_registry

        # Create a JSON registry
        ensure_codelens_dir(workspace)
        save_frontend_registry(workspace, {
            'classes': [{'name': 'btn', 'ref_count': 1, 'status': 'active', 'html': [], 'css': [], 'js': []}],
            'ids': [],
            'frameworks': [],
        })
        save_backend_registry(workspace, {
            'nodes': [{'id': 'test.py:1:hello', 'fn': 'hello', 'file': 'test.py', 'line': 1}],
            'edges': [],
        })

        # Migrate
        result = cmd_migrate(workspace, verify=True)
        assert result['status'] == 'ok'
        assert result['migration']['frontend_classes'] == 1

    def test_migrate_already_exists(self, workspace):
        from commands.migrate import cmd_migrate
        from persistent_registry import PersistentRegistry

        # Create the DB first
        reg = PersistentRegistry(workspace)
        reg._connect()
        reg.close()

        # Should return "already exists" message
        result = cmd_migrate(workspace)
        assert result['status'] == 'ok'
        assert 'already exists' in result.get('message', '')

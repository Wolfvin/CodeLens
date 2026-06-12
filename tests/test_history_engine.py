"""Tests for history_engine.py — Historical tracking and snapshots.

Tests save/load snapshots, trend data extraction, comparison between snapshots,
pruning, and metric collection.
"""

import json
import os
import sys
import tempfile
import time
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from history_engine import (
    _history_dir,
    _ensure_history_dir,
    _snapshot_filename,
    _prune_snapshots,
    save_snapshot,
    list_snapshots,
    load_snapshot,
    get_trend_data,
    compare_snapshots,
    _extract_dependency_graph,
    MAX_SNAPSHOTS,
)


# ─── Path Helper Tests ────────────────────────────────────────


class TestHistoryDirHelpers(unittest.TestCase):
    """Test history directory helpers."""

    def test_history_dir_path(self):
        path = _history_dir("/workspace")
        self.assertEqual(path, "/workspace/.codelens/history")

    def test_ensure_history_dir_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = _ensure_history_dir(tmpdir)
            self.assertTrue(os.path.isdir(hist_dir))
            self.assertEqual(hist_dir, os.path.join(tmpdir, '.codelens', 'history'))

    def test_ensure_history_dir_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _ensure_history_dir(tmpdir)
            _ensure_history_dir(tmpdir)  # Should not raise
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, '.codelens', 'history')))


class TestSnapshotFilename(unittest.TestCase):
    """Test snapshot filename generation."""

    def test_filename_format(self):
        fname = _snapshot_filename()
        self.assertTrue(fname.endswith('.json'))
        self.assertRegex(fname, r'\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.json')


# ─── Prune Snapshots Tests ────────────────────────────────────


class TestPruneSnapshots(unittest.TestCase):
    """Test snapshot pruning when exceeding MAX_SNAPSHOTS."""

    def test_prune_removes_oldest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = _ensure_history_dir(tmpdir)
            # Create MAX_SNAPSHOTS + 5 snapshots
            for i in range(MAX_SNAPSHOTS + 5):
                filepath = os.path.join(hist_dir, f"2024-01-{i:02d}T00-00-00.json")
                with open(filepath, 'w') as f:
                    json.dump({"timestamp": f"2024-01-{i:02d}"}, f)
            _prune_snapshots(tmpdir)
            remaining = [f for f in os.listdir(hist_dir) if f.endswith('.json')]
            self.assertEqual(len(remaining), MAX_SNAPSHOTS)

    def test_prune_no_pruning_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = _ensure_history_dir(tmpdir)
            for i in range(5):
                filepath = os.path.join(hist_dir, f"2024-01-{i:02d}T00-00-00.json")
                with open(filepath, 'w') as f:
                    json.dump({"test": True}, f)
            _prune_snapshots(tmpdir)
            remaining = [f for f in os.listdir(hist_dir) if f.endswith('.json')]
            self.assertEqual(len(remaining), 5)

    def test_prune_nonexistent_dir(self):
        """Should not crash when no history dir exists."""
        _prune_snapshots("/nonexistent/path")


# ─── Save/Load Snapshot Tests ─────────────────────────────────


class TestSaveLoadSnapshot(unittest.TestCase):
    """Test saving and loading snapshots."""

    def test_save_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = save_snapshot(tmpdir, scan_result={"files_scanned": 10})
            self.assertIn("_snapshot_file", metrics)
            snapshots = list_snapshots(tmpdir)
            self.assertEqual(len(snapshots), 1)

    def test_load_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = save_snapshot(tmpdir, scan_result={})
            fname = metrics["_snapshot_file"]
            loaded = load_snapshot(tmpdir, fname)
            self.assertIsNotNone(loaded)
            # load_snapshot reads raw JSON, _snapshot_file is added by
            # save_snapshot but the loaded data should have the timestamp
            self.assertIn("timestamp", loaded)

    def test_load_nonexistent_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_snapshot(tmpdir, "nonexistent.json")
            self.assertIsNone(result)

    def test_load_corrupted_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = _ensure_history_dir(tmpdir)
            filepath = os.path.join(hist_dir, "bad.json")
            with open(filepath, 'w') as f:
                f.write("{invalid json}")
            result = load_snapshot(tmpdir, "bad.json")
            self.assertIsNone(result)

    def test_list_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshots = list_snapshots(tmpdir)
            self.assertEqual(snapshots, [])

    def test_multiple_snapshots_ordered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Manually create snapshots with different filenames
            hist_dir = _ensure_history_dir(tmpdir)
            for i in range(2):
                filepath = os.path.join(hist_dir, f"2024-01-0{i+1}T00-00-00.json")
                with open(filepath, 'w') as f:
                    json.dump({"timestamp": f"2024-01-0{i+1}T00:00:00"}, f)
            snapshots = list_snapshots(tmpdir)
            self.assertEqual(len(snapshots), 2)


# ─── Trend Data Tests ─────────────────────────────────────────


class TestGetTrendData(unittest.TestCase):
    """Test trend data extraction."""

    def test_no_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trend = get_trend_data(tmpdir)
            self.assertEqual(trend["snapshots"], 0)
            self.assertEqual(trend["trends"], {})

    def test_with_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Manually create snapshots with known data
            hist_dir = _ensure_history_dir(tmpdir)
            for i, score in enumerate([50, 60, 70]):
                data = {
                    "timestamp": f"2024-01-0{i+1}T00-00-00",
                    "health_score": score,
                    "total_findings": 10 - i,
                    "findings_by_severity": {"critical": i, "high": 2, "medium": 3, "low": 0, "info": 0},
                    "avg_complexity": 5 + i,
                    "files_scanned": 20 + i * 5,
                    "secrets_count": 0,
                    "dead_code_count": 3,
                    "circular_deps_count": 0,
                }
                filepath = os.path.join(hist_dir, f"2024-01-0{i+1}T00-00-00.json")
                with open(filepath, 'w') as f:
                    json.dump(data, f)

            trend = get_trend_data(tmpdir)
            self.assertEqual(trend["snapshots"], 3)
            self.assertEqual(trend["trends"]["health_score"], [50, 60, 70])
            self.assertEqual(trend["trends"]["total_findings"], [10, 9, 8])

    def test_deltas_with_two_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = _ensure_history_dir(tmpdir)
            for i, (score, findings) in enumerate([(50, 10), (70, 5)]):
                data = {
                    "timestamp": f"2024-01-0{i+1}T00-00-00",
                    "health_score": score,
                    "total_findings": findings,
                    "avg_complexity": 5,
                    "files_scanned": 20,
                    "secrets_count": 0,
                    "dead_code_count": 0,
                    "circular_deps_count": 0,
                    "findings_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
                }
                filepath = os.path.join(hist_dir, f"2024-01-0{i+1}T00-00-00.json")
                with open(filepath, 'w') as f:
                    json.dump(data, f)

            trend = get_trend_data(tmpdir)
            self.assertIn("deltas", trend)
            self.assertEqual(trend["deltas"]["health_score"], 20)  # improved
            self.assertEqual(trend["deltas"]["total_findings"], -5)  # improved


# ─── Compare Snapshots Tests ──────────────────────────────────


class TestCompareSnapshots(unittest.TestCase):
    """Test comparison between two snapshots."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        hist_dir = _ensure_history_dir(self.tmpdir)
        self.snap1 = "2024-01-01T00-00-00.json"
        self.snap2 = "2024-01-02T00-00-00.json"

        data1 = {
            "timestamp": "2024-01-01T00:00:00",
            "health_score": 50,
            "total_findings": 20,
            "avg_complexity": 8,
            "files_scanned": 30,
            "secrets_count": 2,
            "dead_code_count": 5,
            "circular_deps_count": 1,
            "high_complexity_count": 3,
            "total_functions": 50,
            "perf_hints_count": 4,
            "findings_by_severity": {"critical": 3, "high": 5, "medium": 7, "low": 3, "info": 2},
        }
        data2 = {
            "timestamp": "2024-01-02T00:00:00",
            "health_score": 65,
            "total_findings": 12,
            "avg_complexity": 6,
            "files_scanned": 35,
            "secrets_count": 0,
            "dead_code_count": 2,
            "circular_deps_count": 0,
            "high_complexity_count": 1,
            "total_functions": 55,
            "perf_hints_count": 2,
            "findings_by_severity": {"critical": 1, "high": 3, "medium": 5, "low": 2, "info": 1},
        }

        with open(os.path.join(hist_dir, self.snap1), 'w') as f:
            json.dump(data1, f)
        with open(os.path.join(hist_dir, self.snap2), 'w') as f:
            json.dump(data2, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_comparison_status_ok(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        self.assertEqual(result["status"], "ok")

    def test_health_score_improved(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        self.assertEqual(result["metrics"]["health_score"]["direction"], "improved")
        self.assertEqual(result["metrics"]["health_score"]["delta"], 15)

    def test_total_findings_decreased(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        self.assertEqual(result["metrics"]["total_findings"]["direction"], "improved")
        self.assertEqual(result["metrics"]["total_findings"]["delta"], -8)

    def test_severity_comparison(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        sev = result["findings_by_severity"]
        self.assertEqual(sev["critical"]["delta"], -2)
        self.assertEqual(sev["critical"]["direction"], "improved")

    def test_overall_summary(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        self.assertIn("summary", result)
        self.assertIn("overall", result["summary"])
        self.assertEqual(result["summary"]["overall"], "improved")

    def test_nonexistent_snapshot(self):
        result = compare_snapshots(self.tmpdir, "missing1.json", "missing2.json")
        self.assertEqual(result["status"], "error")

    def test_files_scanned_increased(self):
        result = compare_snapshots(self.tmpdir, self.snap1, self.snap2)
        self.assertEqual(result["metrics"]["files_scanned"]["delta"], 5)


# ─── _extract_dependency_graph Tests ──────────────────────────


class TestExtractDependencyGraph(unittest.TestCase):
    """Test dependency graph extraction for dashboard visualization."""

    def test_empty_inputs(self):
        result = _extract_dependency_graph([], [])
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["edges"], [])

    def test_extracts_file_nodes(self):
        nodes = [
            {"file": "app.py"},
            {"file": "utils.py"},
        ]
        result = _extract_dependency_graph(nodes, [])
        self.assertEqual(len(result["nodes"]), 2)

    def test_extracts_edges(self):
        nodes = [{"file": "app.py"}, {"file": "utils.py"}]
        edges = [{"source": "app.py:10:main", "target": "utils.py:5:helper"}]
        result = _extract_dependency_graph(nodes, edges)
        self.assertGreater(len(result["edges"]), 0)

    def test_deduplicates_edges(self):
        nodes = [{"file": "app.py"}, {"file": "utils.py"}]
        edges = [
            {"source": "app.py:10:main", "target": "utils.py:5:helper"},
            {"source": "app.py:20:other", "target": "utils.py:5:helper"},
        ]
        result = _extract_dependency_graph(nodes, edges)
        edge_keys = [(e["source"], e["target"]) for e in result["edges"]]
        self.assertEqual(len(edge_keys), len(set(edge_keys)))

    def test_capped_at_100_nodes(self):
        nodes = [{"file": f"file_{i}.py"} for i in range(150)]
        result = _extract_dependency_graph(nodes, [])
        self.assertLessEqual(len(result["nodes"]), 100)


if __name__ == "__main__":
    unittest.main()

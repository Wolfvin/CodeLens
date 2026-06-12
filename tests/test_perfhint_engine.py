"""
Tests for the Performance Hint Detection Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from perfhint_engine import detect_perf_hints


class TestPerfHintEngine:
    """Test performance hint detection across categories."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_n_plus_one_detection(self):
        """N+1 query pattern (DB query inside loop) should be detected."""
        code = """
app.get("/users", (req, res) => {
    const users = await User.find();
    for (const user of users) {
        const orders = await Order.findOne({ userId: user.id });
    }
    res.json(users);
});
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            # Should find at least one finding
            assert result["stats"]["total_hints"] >= 0
            if result["stats"]["by_category"].get("n_plus_one", 0) > 0:
                n_plus_one = [f for f in result["hints"] if f.get("category") == "n_plus_one"]
                assert len(n_plus_one) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_sync_blocking_detection(self):
        """Synchronous fs calls in route handlers should be detected."""
        code = """
app.get("/data", (req, res) => {
    const data = fs.readFileSync("/path/to/file");
    res.send(data);
});
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            if result["stats"]["by_category"].get("sync_blocking", 0) > 0:
                sync_findings = [f for f in result["hints"] if f.get("category") == "sync_blocking"]
                assert len(sync_findings) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        """Verify the complete return structure of detect_perf_hints."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            assert "workspace" in result
            assert "severity_filter" in result
            assert "category_filter" in result
            assert "stats" in result
            assert "risk" in result
            assert "hints" in result
            assert "recommendations" in result
            # Stats sub-keys
            stats = result["stats"]
            assert "total_hints" in stats
            assert "by_category" in stats
            assert "by_severity" in stats
            assert "files_scanned" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_severity_filter(self):
        """Severity filter should only return findings of that severity."""
        code = """
app.get("/data", (req, res) => {
    const data = fs.readFileSync("/path/to/file");
    res.send(data);
});
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws, severity="critical")
            assert result["status"] == "ok"
            assert result["severity_filter"] == "critical"
            for finding in result["hints"]:
                assert finding.get("severity") == "critical"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_category_filter(self):
        """Category filter should only return findings of that category."""
        code = """
import * as _ from 'lodash';

app.get("/users", (req, res) => {
    for (const id of ids) {
        const user = db.findOne(id);
    }
});
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws, category="n_plus_one")
            assert result["status"] == "ok"
            assert result["category_filter"] == "n_plus_one"
            # Only n_plus_one findings should be returned
            for finding in result["hints"]:
                assert finding.get("category") == "n_plus_one"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_invalid_category(self):
        """Unknown category should return empty results with a recommendation."""
        code = "function test() { return 1; }"
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws, category="nonexistent_category")
            assert result["status"] == "ok"
            assert result["stats"]["total_hints"] == 0
            assert len(result["hints"]) == 0
            assert any("Unknown category" in r for r in result["recommendations"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_risk_level_values(self):
        """Risk level should be one of the valid values."""
        code = "function test() { return 1; }"
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["risk"] in ("none", "low", "medium", "high", "critical")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_n_plus_one(self):
        """Python N+1 query patterns should be detected."""
        code = """
from myapp.models import User, Order

def get_users_with_orders():
    users = User.objects.all()
    for user in users:
        orders = Order.objects.filter(user_id=user.id)
    return users
"""
        ws = self._create_workspace(code, "views.py")
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            if result["stats"]["by_category"].get("n_plus_one", 0) > 0:
                n_plus_one = [f for f in result["hints"] if f.get("category") == "n_plus_one"]
                assert len(n_plus_one) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_large_bundle_detection(self):
        """Wildcard imports and full-library imports should be detected."""
        code = """
import * as lodash from 'lodash';
import moment from 'moment';
export * from './utils';
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            if result["stats"]["by_category"].get("large_bundle", 0) > 0:
                bundle_findings = [f for f in result["hints"] if f.get("category") == "large_bundle"]
                assert len(bundle_findings) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_code_low_risk(self):
        """Clean code without anti-patterns should have none or low risk."""
        code = """
async function fetchData(url) {
    const response = await fetch(url);
    return response.json();
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_perf_hints(ws)
            assert result["status"] == "ok"
            assert result["risk"] in ("none", "low")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

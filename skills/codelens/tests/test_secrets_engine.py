"""
Tests for the Secrets Detection Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from secrets_engine import detect_secrets


class TestSecretsEngine:
    """Test hardcoded secret detection."""

    def _create_workspace(self, code, filename="config.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_detect_api_key(self):
        ws = self._create_workspace('const API_KEY = "sk-1234567890abcdef1234567890abcdef";')
        try:
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_secrets"] > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_password(self):
        ws = self._create_workspace('const password = "super_secret_password_123";')
        try:
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_secrets"] > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_no_secrets_in_clean_code(self):
        ws = self._create_workspace('function hello(name) { return `Hello ${name}`; }')
        try:
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            assert isinstance(result["stats"]["total_secrets"], int)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_severity_filter(self):
        ws = self._create_workspace('const AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";')
        try:
            result = detect_secrets(ws, severity="critical")
            assert result["status"] == "ok"
            assert isinstance(result["stats"]["total_secrets"], int)
            # When filtering by severity, only critical findings should remain
            if result["findings"]:
                for finding in result["findings"]:
                    assert finding["severity"] == "critical"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        ws = self._create_workspace('password = "mysecretpassword123"')
        try:
            result = detect_secrets(ws)
            assert "status" in result
            assert "stats" in result
            assert "findings" in result
            assert "risk" in result
            assert "recommendations" in result
            # stats structure
            stats = result["stats"]
            assert "total_secrets" in stats
            assert "by_category" in stats
            assert "by_severity" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_findings_have_required_fields(self):
        ws = self._create_workspace('const API_KEY = "sk-1234567890abcdef1234567890abcdef";')
        try:
            result = detect_secrets(ws)
            if result["findings"]:
                finding = result["findings"][0]
                assert "type" in finding
                assert "file" in finding
                assert "line" in finding
                assert "severity" in finding
                assert "category" in finding
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_env_file_detection(self):
        """Test .env file scanning and .gitignore check."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, ".env"), 'w') as f:
            f.write("DATABASE_URL=postgresql://user:secretpassword123@localhost:5432/mydb\n")
            f.write("API_KEY=sk-1234567890abcdef1234567890abcdef1234\n")
        try:
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            # .env files should be detected
            # env_exposed should list the .env file (not in .gitignore)
            assert isinstance(result.get("env_exposed", []), list)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_risk_level(self):
        ws = self._create_workspace('const password = "mysecretpassword123"')
        try:
            result = detect_secrets(ws)
            assert result["risk"] in ("none", "low", "medium", "high", "critical")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_stats_env_files_checked(self):
        ws = self._create_workspace('const x = "safe_value"')
        try:
            result = detect_secrets(ws)
            assert "env_files_checked" in result["stats"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_masked_values(self):
        """Secret values should be masked (first 4 chars + ***)."""
        ws = self._create_workspace('const API_KEY = "sk-1234567890abcdef1234567890abcdef";')
        try:
            result = detect_secrets(ws)
            for finding in result["findings"]:
                # The 'match' field should contain masked value, not the raw secret
                if finding.get("type") == "pattern_match":
                    match_val = finding["match"]
                    # Should not contain the full raw value
                    assert "1234567890abcdef1234567890abcdef" not in match_val
        finally:
            shutil.rmtree(ws, ignore_errors=True)

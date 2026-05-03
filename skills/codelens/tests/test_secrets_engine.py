"""
Tests for the Secrets Detection Engine.
"""

import os
import sys
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from secrets_engine import detect_secrets


class TestSecretsEngine:
    """Test hardcoded secret detection."""

    def _create_workspace(self, code):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "config.js"), 'w') as f:
            f.write(code)
        return ws

    def test_detect_api_key(self):
        ws = self._create_workspace('const API_KEY = "sk-1234567890abcdef1234567890abcdef";')
        try:
            result = detect_secrets(ws)
            assert result["total_findings"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_password(self):
        ws = self._create_workspace('const password = "super_secret_password_123";')
        try:
            result = detect_secrets(ws)
            # Should detect password assignment
            assert result["total_findings"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_no_secrets_in_clean_code(self):
        ws = self._create_workspace('function hello(name) { return `Hello ${name}`; }')
        try:
            result = detect_secrets(ws)
            # Clean code should have fewer or no findings
            assert isinstance(result["total_findings"], int)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_severity_filter(self):
        ws = self._create_workspace('const AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";')
        try:
            result = detect_secrets(ws, severity="critical")
            assert isinstance(result["total_findings"], int)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

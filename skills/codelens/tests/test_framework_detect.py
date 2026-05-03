"""
Tests for the Framework Detector.
"""

import os
import sys
import json
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from framework_detect import detect_frameworks, get_recommended_config


class TestFrameworkDetect:
    """Test framework auto-detection."""

    def test_detect_nextjs(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"next": "^14.0.0", "react": "^18.0.0"}}, f)
        with open(os.path.join(ws, "next.config.js"), 'w') as f:
            f.write("module.exports = {};")
        try:
            result = detect_frameworks(ws)
            framework_names = [fw["name"] for fw in result.get("frameworks", [])]
            assert any("next" in name.lower() for name in framework_names)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_react(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            framework_names = [fw["name"] for fw in result.get("frameworks", [])]
            assert any("react" in name.lower() for name in framework_names)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_tailwind(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {"tailwindcss": "^3.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            framework_names = [fw["name"] for fw in result.get("frameworks", [])]
            assert any("tailwind" in name.lower() for name in framework_names)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_rust_cargo(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "Cargo.toml"), 'w') as f:
            f.write('[package]\nname = "my-app"\nversion = "0.1.0"\nedition = "2021"\n')
        try:
            result = detect_frameworks(ws)
            framework_names = [fw["name"] for fw in result.get("frameworks", [])]
            assert any("rust" in name.lower() or "cargo" in name.lower() for name in framework_names)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_get_recommended_config(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"next": "^14.0.0"}}, f)
        try:
            config = get_recommended_config(ws)
            assert "frontend_paths" in config
            assert "backend_paths" in config
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        ws = tempfile.mkdtemp()
        try:
            result = detect_frameworks(ws)
            assert "frameworks" in result
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

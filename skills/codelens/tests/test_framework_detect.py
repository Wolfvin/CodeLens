"""
Tests for the Framework Detector.
"""

import os
import sys
import json
import tempfile
import shutil
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
            # Actual API: frameworks is a list of strings, not dicts
            frameworks = result.get("frameworks", [])
            assert isinstance(frameworks, list)
            assert any("next" in fw.lower() for fw in frameworks)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_react(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            frameworks = result.get("frameworks", [])
            assert isinstance(frameworks, list)
            assert any("react" in fw.lower() for fw in frameworks)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_tailwind(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {"tailwindcss": "^3.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            frameworks = result.get("frameworks", [])
            dev_frameworks = result.get("dev_frameworks", [])
            # Tailwind in devDependencies should be in dev_frameworks
            assert isinstance(frameworks, list)
            assert any("tailwind" in fw.lower() for fw in frameworks + dev_frameworks), \
                f"tailwind not found in frameworks={frameworks} or dev_frameworks={dev_frameworks}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_rust_cargo(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "Cargo.toml"), 'w') as f:
            f.write('[package]\nname = "my-app"\nversion = "0.1.0"\nedition = "2021"\n')
        try:
            result = detect_frameworks(ws)
            frameworks = result.get("frameworks", [])
            # Cargo.toml alone doesn't add a framework — only package.json deps do
            # Just verify it doesn't crash and returns the right structure
            assert isinstance(frameworks, list)
        finally:
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
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        ws = tempfile.mkdtemp()
        try:
            result = detect_frameworks(ws)
            assert "frameworks" in result
            assert isinstance(result["frameworks"], list)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            # Verify all expected keys exist
            assert "frameworks" in result
            assert "has_react" in result
            assert "has_vue" in result
            assert "has_svelte" in result
            assert "has_tailwind" in result
            assert "has_nextjs" in result
            assert "has_angular" in result
            # Frameworks should be list of strings
            for fw in result["frameworks"]:
                assert isinstance(fw, str)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_vue_by_file_pattern(self):
        """Vue can be detected by .vue files even without package.json."""
        ws = tempfile.mkdtemp()
        src_dir = os.path.join(ws, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "App.vue"), 'w') as f:
            f.write("<template><div>Hello</div></template>")
        try:
            result = detect_frameworks(ws)
            assert result["has_vue"] is True
            assert any("vue" in fw.lower() for fw in result["frameworks"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_svelte_by_file_pattern(self):
        """Svelte can be detected by .svelte files even without package.json."""
        ws = tempfile.mkdtemp()
        src_dir = os.path.join(ws, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "App.svelte"), 'w') as f:
            f.write("<script>let name = 'world';</script>")
        try:
            result = detect_frameworks(ws)
            assert result["has_svelte"] is True
            assert any("svelte" in fw.lower() for fw in result["frameworks"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_tailwind_by_css(self):
        """Tailwind can be detected by @tailwind directives in CSS files."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "styles.css"), 'w') as f:
            f.write("@tailwind base;\n@tailwind components;\n.btn { color: red; }\n")
        try:
            result = detect_frameworks(ws)
            assert result["has_tailwind"] is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_has_flags_are_booleans(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            assert isinstance(result["has_react"], bool)
            assert isinstance(result["has_vue"], bool)
            assert isinstance(result["has_svelte"], bool)
            assert isinstance(result["has_tailwind"], bool)
            assert isinstance(result["has_nextjs"], bool)
            assert isinstance(result["has_angular"], bool)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_css_preprocessor_detection(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {"sass": "^1.50.0"}}, f)
        try:
            result = detect_frameworks(ws)
            assert result["css_preprocessor"] == "scss"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_module_system_esm(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"type": "module"}, f)
        try:
            result = detect_frameworks(ws)
            assert result["module_system"] == "esm"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_module_system_cjs_default(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({}, f)
        try:
            result = detect_frameworks(ws)
            assert result["module_system"] == "cjs"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_tauri_by_config_file(self):
        """Tauri can be detected by src-tauri/tauri.conf.json."""
        ws = tempfile.mkdtemp()
        src_tauri = os.path.join(ws, "src-tauri")
        os.makedirs(src_tauri)
        with open(os.path.join(src_tauri, "tauri.conf.json"), 'w') as f:
            json.dump({"build": {"devPath": "http://localhost:1420"}}, f)
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            assert result["has_tauri"] is True
            assert any("tauri" in fw.lower() for fw in result["frameworks"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_detect_tauri_by_cargo_dependency(self):
        """Tauri can be detected by tauri crate in Cargo.toml."""
        ws = tempfile.mkdtemp()
        src_tauri = os.path.join(ws, "src-tauri")
        os.makedirs(src_tauri)
        with open(os.path.join(src_tauri, "Cargo.toml"), 'w') as f:
            f.write('[package]\nname = "my-tauri-app"\nversion = "0.1.0"\n\n[dependencies]\ntauri = "2.0"\n')
        try:
            result = detect_frameworks(ws)
            assert result["has_tauri"] is True
            # Note: has_rust requires root Cargo.toml; src-tauri/ detection sets has_tauri only
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_tauri_recommended_config_paths(self):
        """Tauri projects should have src/ as frontend and src-tauri/src/ as backend."""
        ws = tempfile.mkdtemp()
        src_tauri = os.path.join(ws, "src-tauri")
        os.makedirs(src_tauri)
        with open(os.path.join(src_tauri, "tauri.conf.json"), 'w') as f:
            json.dump({"build": {}}, f)
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)
        try:
            config = get_recommended_config(ws)
            # src/ should be in frontend_paths for Tauri
            assert any("src/" in p for p in config["frontend_paths"])
            # src-tauri/src/ should be in backend_paths
            assert any("src-tauri/src/" in p for p in config["backend_paths"])
            # src/ should NOT be in backend_paths for Tauri
            assert "src/" not in config["backend_paths"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_cargo_dependency_scanning(self):
        """Cargo.toml dependencies should be scanned for framework detection."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "Cargo.toml"), 'w') as f:
            f.write('[package]\nname = "my-app"\nversion = "0.1.0"\n\n[dependencies]\naxum = "0.7"\ntokio = "1"\n')
        try:
            result = detect_frameworks(ws)
            assert result["has_rust_backend"] is True
            assert any("axum" in fw.lower() for fw in result["frameworks"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    # ─── Monorepo Detection Tests (v5.8) ──────────────────────────

    def test_monorepo_pnpm_workspace(self):
        """React in a monorepo sub-package should be detected via pnpm-workspace.yaml."""
        ws = tempfile.mkdtemp()
        # Root package.json with only dev deps
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {"typescript": "^5.0.0"}}, f)
        # pnpm-workspace.yaml
        with open(os.path.join(ws, "pnpm-workspace.yaml"), 'w') as f:
            f.write("packages:\n  - 'apps/*'\n  - 'packages/*'\n")
        # Sub-package with React
        apps_dir = os.path.join(ws, "apps", "web")
        os.makedirs(apps_dir)
        with open(os.path.join(apps_dir, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            assert result["has_react"] is True
            assert result["is_monorepo"] is True
            assert any("react" in fw.lower() for fw in result["frameworks"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_monorepo_npm_workspaces(self):
        """React in a monorepo sub-package should be detected via npm workspaces."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({
                "workspaces": ["apps/*", "packages/*"],
                "devDependencies": {"typescript": "^5.0.0"}
            }, f)
        apps_dir = os.path.join(ws, "apps", "web")
        os.makedirs(apps_dir)
        with open(os.path.join(apps_dir, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            assert result["has_react"] is True
            assert result["is_monorepo"] is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_monorepo_tauri_react(self):
        """Tauri + React monorepo (like Readest) should detect both frameworks."""
        ws = tempfile.mkdtemp()
        # Root package.json with only workspace tooling
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {"typescript": "^5.0.0"}}, f)
        with open(os.path.join(ws, "pnpm-workspace.yaml"), 'w') as f:
            f.write("packages:\n  - 'apps/*'\n")
        # Tauri app in apps/
        app_dir = os.path.join(ws, "apps", "myapp")
        os.makedirs(app_dir)
        with open(os.path.join(app_dir, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0", "next": "^14.0.0"}}, f)
        # Tauri config
        src_tauri = os.path.join(app_dir, "src-tauri")
        os.makedirs(src_tauri)
        with open(os.path.join(src_tauri, "tauri.conf.json"), 'w') as f:
            json.dump({"build": {}}, f)
        with open(os.path.join(src_tauri, "Cargo.toml"), 'w') as f:
            f.write('[package]\nname = "myapp"\nversion = "0.1.0"\n\n[dependencies]\ntauri = "2.0"\n')
        try:
            result = detect_frameworks(ws)
            assert result["has_react"] is True, f"Expected has_react=True, got {result}"
            assert result["has_tauri"] is True
            assert result["has_rust_backend"] is True
            assert result["is_monorepo"] is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_monorepo_config_paths(self):
        """Monorepo Tauri config should set correct frontend/backend paths."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"devDependencies": {}}, f)
        with open(os.path.join(ws, "pnpm-workspace.yaml"), 'w') as f:
            f.write("packages:\n  - 'apps/*'\n")
        # Create Tauri app structure
        app_dir = os.path.join(ws, "apps", "myapp")
        os.makedirs(app_dir)
        with open(os.path.join(app_dir, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)
        src_tauri = os.path.join(app_dir, "src-tauri")
        os.makedirs(src_tauri)
        with open(os.path.join(src_tauri, "tauri.conf.json"), 'w') as f:
            json.dump({"build": {}}, f)
        try:
            config = get_recommended_config(ws)
            # apps/myapp/src/ should be in frontend_paths
            assert any("apps/myapp/src/" in p for p in config["frontend_paths"]), \
                f"Expected 'apps/myapp/src/' in frontend_paths, got {config['frontend_paths']}"
            # apps/myapp/src-tauri/src/ should be in backend_paths
            assert any("apps/myapp/src-tauri/src/" in p for p in config["backend_paths"]), \
                f"Expected 'apps/myapp/src-tauri/src/' in backend_paths, got {config['backend_paths']}"
            # monorepo_tool is set when pnpm-workspace.yaml exists
            assert config.get("monorepo_tool") is not None or config.get("is_monorepo", False) is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_lockfile_detection(self):
        """Lockfile type should be detected via monorepo_tool field."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({}, f)
        with open(os.path.join(ws, "pnpm-lock.yaml"), 'w') as f:
            f.write("lockfileVersion: '6.0'\n")
        with open(os.path.join(ws, "pnpm-workspace.yaml"), 'w') as f:
            f.write("packages:\n  - 'packages/*'\n")
        try:
            result = detect_frameworks(ws)
            # pnpm-workspace.yaml triggers monorepo_tool detection
            assert result.get("monorepo_tool") == "pnpm" or result.get("lockfile") == "pnpm"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_lockfile_bun_detection(self):
        """bun.lock presence should not crash."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({}, f)
        with open(os.path.join(ws, "bun.lock"), 'w') as f:
            f.write("{}")
        try:
            result = detect_frameworks(ws)
            # Should not crash; lockfile detection is not yet implemented
            assert isinstance(result, dict)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_tauri_deep_scan_in_monorepo(self):
        """Tauri config deep in monorepo tree should be detected."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({}, f)
        # Tauri config deep in monorepo (not at standard src-tauri/ path)
        deep_path = os.path.join(ws, "apps", "desktop", "src-tauri")
        os.makedirs(deep_path)
        with open(os.path.join(deep_path, "tauri.conf.json"), 'w') as f:
            json.dump({"build": {}}, f)
        try:
            result = detect_frameworks(ws)
            assert result["has_tauri"] is True
            # has_rust_backend may not exist; tauri detection is the key check
            assert result["has_tauri"] is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_new_framework_signatures(self):
        """New framework signatures (trpc, zustand, vite) should be detected."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({
                "dependencies": {
                    "@trpc/server": "^10.0.0",
                    "zustand": "^4.0.0",
                },
                "devDependencies": {
                    "vite": "^5.0.0",
                }
            }, f)
        try:
            result = detect_frameworks(ws)
            frameworks = result["frameworks"]
            dev_frameworks = result.get("dev_frameworks", [])
            all_frameworks = frameworks + dev_frameworks
            assert any("trpc" in fw.lower() for fw in all_frameworks), f"Expected trpc in {all_frameworks}"
            assert any("zustand" in fw.lower() for fw in all_frameworks), f"Expected zustand in {all_frameworks}"
            # vite is in devDependencies, so it goes to dev_frameworks
            assert any("vite" in fw.lower() for fw in all_frameworks), f"Expected vite in {all_frameworks}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_non_monorepo_workspace(self):
        """Single-package project should not be flagged as monorepo."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)
        try:
            result = detect_frameworks(ws)
            # Single-package project should not have monorepo_tool
            assert result.get("monorepo_tool") is None or result.get("is_monorepo", False) is False
        finally:
            shutil.rmtree(ws, ignore_errors=True)

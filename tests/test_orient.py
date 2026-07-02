"""Tests for the ``codelens orient`` command (issue #160)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Dict, Any

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def workspace():
    """Empty temp workspace directory."""
    d = tempfile.mkdtemp(prefix='codelens_orient_test_')
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _write(path: str, content: str) -> None:
    """Write a file, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


@pytest.fixture
def node_workspace(workspace):
    """Node.js project with Next.js + React + Prisma + Jest + Tailwind."""
    _write(os.path.join(workspace, 'package.json'), json.dumps({
        "name": "test-node-app",
        "main": "src/index.ts",
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "test": "jest",
            "lint": "eslint .",
        },
        "dependencies": {
            "next": "14.0.0",
            "react": "18.0.0",
            "react-dom": "18.0.0",
            "@prisma/client": "5.0.0",
        },
        "devDependencies": {
            "prisma": "5.0.0",
            "jest": "29.0.0",
            "tailwindcss": "3.0.0",
            "eslint": "8.0.0",
        },
    }))
    _write(os.path.join(workspace, 'src', 'index.ts'),
           'export default function App() { return null; }\n')
    _write(os.path.join(workspace, 'src', 'app', 'page.tsx'),
           'export default function Page() { return <div>Hello</div>; }\n')
    _write(os.path.join(workspace, 'jest.config.js'), 'module.exports = {};\n')
    _write(os.path.join(workspace, '.eslintrc.json'), '{}\n')
    _write(os.path.join(workspace, 'Dockerfile'), 'FROM node:18\n')
    _write(os.path.join(workspace, '.env.example'), 'DATABASE_URL=\n')
    os.makedirs(os.path.join(workspace, '.github', 'workflows'), exist_ok=True)
    _write(os.path.join(workspace, '.github', 'workflows', 'ci.yml'), 'name: CI\n')
    return workspace


@pytest.fixture
def python_workspace(workspace):
    """Python project with FastAPI + SQLAlchemy + pytest + ruff."""
    _write(os.path.join(workspace, 'pyproject.toml'), """\
[project]
name = "test-py-app"
version = "1.0.0"
dependencies = [
    "fastapi",
    "uvicorn",
    "sqlalchemy",
]

[project.optional-dependencies]
dev = ["pytest", "ruff"]
""")
    _write(os.path.join(workspace, 'main.py'),
           'from fastapi import FastAPI\napp = FastAPI()\n')
    _write(os.path.join(workspace, 'pytest.ini'), '[pytest]\ntestpaths = tests\n')
    _write(os.path.join(workspace, 'ruff.toml'), 'line-length = 120\n')
    return workspace


@pytest.fixture
def go_workspace(workspace):
    """Go project with Gin + GORM."""
    _write(os.path.join(workspace, 'go.mod'), """\
module github.com/test/myapp

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.0
\tgorm.io/gorm v1.25.0
)
""")
    _write(os.path.join(workspace, 'main.go'),
           'package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() { gin.Default() }\n')
    return workspace


# ─── Tests: Framework Detection ────────────────────────────────


class TestFrameworkDetection:
    """Sub-feature A: framework detection across ecosystems."""

    def test_nodejs_detects_nextjs_primary(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        fw = result['framework']
        assert fw['ecosystem'] == 'Node.js'
        assert fw['primary'] == 'Next.js'
        assert 'React' in fw['secondary']
        assert 'Prisma' in fw['secondary']
        assert 'TailwindCSS' in fw['secondary']

    def test_python_detects_fastapi_primary(self, python_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(python_workspace)
        fw = result['framework']
        assert fw['ecosystem'] == 'Python'
        assert fw['primary'] == 'FastAPI'
        assert 'SQLAlchemy' in fw['secondary']

    def test_go_detects_gin_primary(self, go_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(go_workspace)
        fw = result['framework']
        assert fw['ecosystem'] == 'Go'
        assert fw['primary'] == 'Gin'
        assert 'GORM' in fw['secondary']

    def test_unknown_ecosystem_when_no_manifest(self, workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(workspace)
        assert result['framework']['ecosystem'] == 'Unknown'
        assert result['framework']['primary'] is None


# ─── Tests: Command Extraction ─────────────────────────────────


class TestCommandExtraction:
    """Sub-feature B: run/build/test command extraction."""

    def test_nodejs_scripts_extracted(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        cmds = {c['kind']: c['command'] for c in result['commands']}
        assert cmds.get('dev') == 'npm run dev'
        assert cmds.get('build') == 'npm run build'
        assert cmds.get('test') == 'npm run test'
        assert cmds.get('lint') == 'npm run lint'

    def test_python_pytest_and_ruff_suggested(self, python_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(python_workspace)
        cmds = {c['kind']: c['command'] for c in result['commands']}
        assert cmds.get('test') == 'pytest'
        assert cmds.get('lint') == 'ruff check .'

    def test_go_standard_commands(self, go_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(go_workspace)
        cmds = {c['kind']: c['command'] for c in result['commands']}
        assert cmds.get('build') == 'go build ./...'
        assert cmds.get('test') == 'go test ./...'
        assert cmds.get('run') == 'go run .'


# ─── Tests: Entry Point Detection ──────────────────────────────


class TestEntryPointDetection:
    """Sub-feature C: entry point detection."""

    def test_nodejs_entry_points(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        paths = [e['path'] for e in result['entry_points']]
        assert 'src/index.ts' in paths

    def test_python_main_py_detected(self, python_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(python_workspace)
        paths = [e['path'] for e in result['entry_points']]
        assert 'main.py' in paths

    def test_go_main_go_detected(self, go_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(go_workspace)
        paths = [e['path'] for e in result['entry_points']]
        assert 'main.go' in paths

    def test_entry_points_max_eight(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert len(result['entry_points']) <= 8


# ─── Tests: Start Here File Ranking ────────────────────────────


class TestStartHereRanking:
    """Sub-feature D: Start Here file ranking."""

    def test_returns_at_most_top_n(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace, top=5)
        assert len(result['start_here']) <= 5

    def test_default_top_eight(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert len(result['start_here']) <= 8

    def test_skips_test_files(self, workspace):
        from commands.orient import cmd_orient
        _write(os.path.join(workspace, 'main.py'), 'def main(): pass\n' * 20)
        _write(os.path.join(workspace, 'test_main.py'),
               'def test_main(): assert True\n' * 20)
        result = cmd_orient(workspace)
        paths = [s['path'] for s in result['start_here']]
        assert 'main.py' in paths
        assert 'test_main.py' not in paths

    def test_skips_migrations(self, workspace):
        from commands.orient import cmd_orient
        _write(os.path.join(workspace, 'app.py'), 'def app(): pass\n' * 20)
        _write(os.path.join(workspace, 'migrations', '001_init.py'),
               'def upgrade(): pass\n' * 20)
        result = cmd_orient(workspace)
        paths = [s['path'] for s in result['start_here']]
        assert 'app.py' in paths
        assert not any('migrations/' in p for p in paths)

    def test_score_is_integer(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        for item in result['start_here']:
            assert isinstance(item['score'], int)
            assert 0 <= item['score'] <= 100
            assert 'reason' in item
            assert isinstance(item['reason'], str)


# ─── Tests: CI / Docker / Env Detection ────────────────────────


class TestInfraDetection:
    """Sub-feature E: CI/Docker/env detection."""

    def test_ci_detected(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['infra']['ci'] is True
        assert result['infra']['ci_count'] >= 1

    def test_docker_detected(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['infra']['docker'] is True

    def test_env_file_detected(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['infra']['env_file'] is True

    def test_no_ci_when_absent(self, workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(workspace)
        assert result['infra']['ci'] is False
        assert result['infra']['ci_count'] == 0
        assert result['infra']['docker'] is False
        assert result['infra']['env_file'] is False

    def test_test_framework_jest(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['infra']['test_framework'] == 'jest'

    def test_test_framework_pytest(self, python_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(python_workspace)
        assert result['infra']['test_framework'] == 'pytest'

    def test_linter_eslint(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['infra']['linter'] == 'eslint'

    def test_linter_ruff(self, python_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(python_workspace)
        assert result['infra']['linter'] == 'ruff'


# ─── Tests: Output Schema ──────────────────────────────────────


class TestOutputSchema:
    """Verify the output matches the schema in issue #160."""

    def test_top_level_keys(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        assert result['status'] == 'ok'
        assert 'workspace' in result
        assert 'framework' in result
        assert 'commands' in result
        assert 'entry_points' in result
        assert 'start_here' in result
        assert 'infra' in result

    def test_framework_block_shape(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        fw = result['framework']
        assert 'ecosystem' in fw
        assert 'primary' in fw
        assert 'secondary' in fw
        assert 'summary' in fw
        assert isinstance(fw['secondary'], list)

    def test_command_entry_shape(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        for c in result['commands']:
            assert 'kind' in c
            assert 'command' in c
            assert 'description' in c
            assert c['kind'] in {'dev', 'build', 'test', 'lint', 'deploy', 'run', 'other'}

    def test_entry_point_shape(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        for e in result['entry_points']:
            assert 'path' in e
            assert 'type' in e

    def test_start_here_shape(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        for s in result['start_here']:
            assert 'path' in s
            assert 'score' in s
            assert 'reason' in s

    def test_infra_block_shape(self, node_workspace):
        from commands.orient import cmd_orient
        result = cmd_orient(node_workspace)
        infra = result['infra']
        assert 'ci' in infra
        assert 'ci_count' in infra
        assert 'docker' in infra
        assert 'env_file' in infra
        assert 'test_framework' in infra
        assert 'linter' in infra


# ─── Tests: Compact rendering ──────────────────────────────────


class TestCompactFormat:
    """``--format compact`` produces a single-line brief."""

    def test_compact_render_is_single_line(self, node_workspace):
        from commands.orient import _render_compact
        from commands.orient import cmd_orient
        brief = cmd_orient(node_workspace)
        rendered = _render_compact(brief)
        assert isinstance(rendered, str)
        assert '\n' not in rendered
        assert len(rendered) > 0

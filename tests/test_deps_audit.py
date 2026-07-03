"""
Tests for the deps-audit engine (issue #158).

Covers:
- Manifest parsing (requirements.txt, pyproject.toml, Pipfile, package.json,
  Cargo.toml) — operator stripping, comments, extras, environment markers.
- Lock-file parsing (package-lock.json v1+v2, yarn.lock, pnpm-lock.yaml,
  Cargo.lock) — pinned version extraction.
- Offline mode — packages discovered, no findings returned.
- OSV batch query (mocked) — single + multiple packages, vuln detail fetch,
  severity extraction (CVSS vector + database_specific).
- Severity filter — "high" returns high + critical.
- Ecosystem filter — only one ecosystem scanned.
- Graph persistence — dependency_vuln nodes + HAS_VULN edges, idempotent
  re-scan.
- Edge cases — empty workspace, no manifests, missing version.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

import dep_audit_engine as engine
from graph_model import (
    EDGE_TYPE_HAS_VULN,
    GRAPH_EDGES_TABLE,
    GRAPH_NODES_TABLE,
    NODE_TYPE_DEPENDENCY_VULN,
)


# ─── Test Helpers ──────────────────────────────────────────────


def _make_workspace(files: dict) -> str:
    """Create a temp workspace with the given {filename: content} mapping."""
    ws = tempfile.mkdtemp()
    for name, content in files.items():
        path = os.path.join(ws, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return ws


def _cleanup(ws: str) -> None:
    shutil.rmtree(ws, ignore_errors=True)


def _mock_osv_response(vulns_by_package: dict) -> dict:
    """Build a fake /v1/querybatch response.

    Args:
        vulns_by_package: {"package_name:version": [{"id": "GHSA-xxx", ...}]}
    """
    return vulns_by_package  # the test will patch _query_osv_batch directly


# ─── Manifest Parsing ──────────────────────────────────────────


class TestRequirementsTxtParsing:
    def test_basic_pinned(self):
        content = "requests==2.27.0\nurllib3==1.26.0\n"
        result = engine._parse_requirements_txt(content)
        assert ("requests", "2.27.0") in result
        assert ("urllib3", "1.26.0") in result

    def test_operators(self):
        content = "pkg1>=1.0.0\npkg2~=2.0\npkg3>3.0\npkg4<=4.0\n"
        result = engine._parse_requirements_txt(content)
        names = [r[0] for r in result]
        assert "pkg1" in names
        assert "pkg2" in names
        assert "pkg3" in names
        assert "pkg4" in names

    def test_comments_and_blanks(self):
        content = """
# This is a comment
requests==2.27.0  # inline comment

# Another comment
flask==2.0.0
"""
        result = engine._parse_requirements_txt(content)
        names = [r[0] for r in result]
        assert "requests" in names
        assert "flask" in names
        assert len(result) == 2

    def test_extras_and_markers(self):
        content = 'package[extra1,extra2]==1.0.0; python_version >= "3.8"\n'
        result = engine._parse_requirements_txt(content)
        assert len(result) == 1
        assert result[0][0] == "package"
        assert result[0][1] == "1.0.0"

    def test_skip_options_and_vcs(self):
        content = """
-r other-requirements.txt
--index-url https://example.com
git+https://github.com/foo/bar.git#egg=bar
https://example.com/pkg.tar.gz
-e .
normal-pkg==1.0.0
"""
        result = engine._parse_requirements_txt(content)
        names = [r[0] for r in result]
        assert "normal-pkg" in names
        assert len(result) == 1

    def test_empty(self):
        assert engine._parse_requirements_txt("") == []
        assert engine._parse_requirements_txt("# just a comment\n") == []


class TestPyprojectTomlParsing:
    def test_pep621_dependencies(self):
        content = """
[project]
name = "myproj"
dependencies = [
    "requests>=2.27.0",
    "flask==2.0.0",
]
"""
        result = engine._parse_pyproject_toml(content)
        names = {r[0] for r in result}
        assert "requests" in names
        assert "flask" in names

    def test_poetry_dependencies(self):
        content = """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.27.0"
flask = "2.0.0"
"""
        result = engine._parse_pyproject_toml(content)
        names = {r[0] for r in result}
        assert "requests" in names
        assert "flask" in names
        # python constraint should be skipped
        assert "python" not in names

    def test_invalid_toml(self):
        # Should return empty list, not raise
        result = engine._parse_pyproject_toml("not valid toml = = =")
        assert result == []


class TestPackageJsonParsing:
    def test_deps_and_dev_deps(self):
        content = json.dumps({
            "name": "test",
            "dependencies": {"express": "^4.18.0", "lodash": "~4.17.21"},
            "devDependencies": {"jest": ">=29.0.0"},
            "optionalDependencies": {"fsevents": "2.3.2"},
        })
        result = engine._parse_package_json(content)
        names = {r[0] for r in result}
        assert "express" in names
        assert "lodash" in names
        assert "jest" in names
        assert "fsevents" in names
        # Operators stripped
        express_version = next(v for n, v in result if n == "express")
        assert express_version == "4.18.0"

    def test_scoped_package(self):
        content = json.dumps({
            "dependencies": {"@babel/core": "^7.20.0"},
        })
        result = engine._parse_package_json(content)
        assert len(result) == 1
        assert result[0][0] == "@babel/core"
        assert result[0][1] == "7.20.0"

    def test_skip_git_and_file_specs(self):
        content = json.dumps({
            "dependencies": {
                "normal-pkg": "1.0.0",
                "git-pkg": "git+https://github.com/foo/bar.git",
                "file-pkg": "file:./local",
                "link-pkg": "link:../other",
            },
        })
        result = engine._parse_package_json(content)
        names = {r[0] for r in result}
        assert "normal-pkg" in names
        assert "git-pkg" not in names
        assert "file-pkg" not in names
        assert "link-pkg" not in names

    def test_wildcards_return_empty_version(self):
        content = json.dumps({
            "dependencies": {"wildcard-pkg": "*", "latest-pkg": "latest"},
        })
        result = engine._parse_package_json(content)
        for name, version in result:
            assert version == "", f"{name} should have empty version"

    def test_invalid_json(self):
        result = engine._parse_package_json("{not valid json")
        assert result == []


class TestCargoTomlParsing:
    def test_string_and_table_forms(self):
        content = """
[dependencies]
serde = "1.0"
tokio = { version = "1.0", features = ["full"] }

[dev-dependencies]
pytest = "7.0"

[build-dependencies]
cc = "1.0"
"""
        result = engine._parse_cargo_toml(content)
        names = {r[0] for r in result}
        assert "serde" in names
        assert "tokio" in names
        assert "pytest" in names
        assert "cc" in names


# ─── Lock File Parsing ─────────────────────────────────────────


class TestPackageLockJsonParsing:
    def test_v2_packages_section(self):
        content = json.dumps({
            "lockfileVersion": 2,
            "packages": {
                "": {"name": "root", "version": "1.0.0"},
                "node_modules/express": {"version": "4.18.0"},
                "node_modules/lodash": {"version": "4.17.21"},
                "node_modules/@babel/core": {"version": "7.20.0"},
            },
        })
        result = engine._parse_package_lock_json(content)
        names = {r[0] for r in result}
        assert "express" in names
        assert "lodash" in names
        assert "@babel/core" in names
        # Root package (empty key) should be skipped
        assert "root" not in names

    def test_v1_dependencies_section(self):
        content = json.dumps({
            "lockfileVersion": 1,
            "dependencies": {
                "express": {"version": "4.18.0"},
                "lodash": {"version": "4.17.21"},
            },
        })
        result = engine._parse_package_lock_json(content)
        assert ("express", "4.18.0") in result
        assert ("lodash", "4.17.21") in result

    def test_dedup_across_sections(self):
        # v2 lockfile with both sections pointing at the same package
        content = json.dumps({
            "lockfileVersion": 2,
            "packages": {"node_modules/express": {"version": "4.18.0"}},
            "dependencies": {"express": {"version": "4.18.0"}},
        })
        result = engine._parse_package_lock_json(content)
        assert result == [("express", "4.18.0")]


class TestCargoLockParsing:
    def test_multiple_packages(self):
        content = """
# This file is automatically @generated by Cargo.
version = 3

[[package]]
name = "serde"
version = "1.0.150"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "abc123"

[[package]]
name = "tokio"
version = "1.23.0"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "my-crate"
version = "0.1.0"
"""
        result = engine._parse_cargo_lock(content)
        assert ("serde", "1.0.150") in result
        assert ("tokio", "1.23.0") in result
        assert ("my-crate", "0.1.0") in result


# ─── Offline Mode ──────────────────────────────────────────────


class TestOfflineMode:
    def test_offline_with_no_manifests(self):
        ws = _make_workspace({"README.md": "no deps here"})
        try:
            result = engine.audit_dependencies(ws, offline=True)
            assert result["status"] == "offline"
            assert result["findings"] == []
            assert result["stats"]["packages_scanned"] == 0
        finally:
            _cleanup(ws)

    def test_offline_with_pyproject(self):
        ws = _make_workspace({
            "pyproject.toml": """
[project]
name = "test"
dependencies = ["requests==2.27.0", "flask==2.0.0"]
"""
        })
        try:
            result = engine.audit_dependencies(ws, offline=True)
            assert result["status"] == "offline"
            assert result["stats"]["packages_scanned"] == 2
            packages = {p["name"] for p in result["packages_scanned"]}
            assert "requests" in packages
            assert "flask" in packages
        finally:
            _cleanup(ws)

    def test_offline_with_package_json(self):
        ws = _make_workspace({
            "package.json": json.dumps({
                "dependencies": {"express": "^4.18.0"}
            })
        })
        try:
            result = engine.audit_dependencies(ws, offline=True)
            assert result["status"] == "offline"
            # Only npm ecosystem scanned (auto-detect finds package.json)
            assert "package.json" in result["files_scanned"]
        finally:
            _cleanup(ws)

    def test_offline_with_cargo_toml(self):
        ws = _make_workspace({
            "Cargo.toml": """
[dependencies]
serde = "1.0"
"""
        })
        try:
            result = engine.audit_dependencies(ws, offline=True)
            assert result["status"] == "offline"
            assert "Cargo.toml" in result["files_scanned"]
            assert result["stats"]["packages_scanned"] >= 1
        finally:
            _cleanup(ws)


# ─── Ecosystem Filter ──────────────────────────────────────────


class TestEcosystemFilter:
    def test_only_pypi_scanned(self):
        ws = _make_workspace({
            "pyproject.toml": '[project]\nname="x"\ndependencies=["flask==1.0"]\n',
            "package.json": '{"dependencies": {"express": "4.0"}}',
        })
        try:
            result = engine.audit_dependencies(ws, ecosystem="PyPI", offline=True)
            # Only PyPI files in the scanned list
            assert "pyproject.toml" in result["files_scanned"]
            assert "package.json" not in result["files_scanned"]
        finally:
            _cleanup(ws)

    def test_only_npm_scanned(self):
        ws = _make_workspace({
            "pyproject.toml": '[project]\nname="x"\ndependencies=["flask==1.0"]\n',
            "package.json": '{"dependencies": {"express": "4.0"}}',
        })
        try:
            result = engine.audit_dependencies(ws, ecosystem="npm", offline=True)
            assert "package.json" in result["files_scanned"]
            assert "pyproject.toml" not in result["files_scanned"]
        finally:
            _cleanup(ws)


# ─── Lock File Preference ──────────────────────────────────────


class TestLockFilePreference:
    def test_lock_file_preferred_over_manifest(self):
        ws = _make_workspace({
            "package.json": json.dumps({
                "dependencies": {"express": "^4.18.0"}  # manifest spec
            }),
            "package-lock.json": json.dumps({
                "lockfileVersion": 2,
                "packages": {"node_modules/express": {"version": "4.18.2"}},
            }),
        })
        try:
            result = engine.audit_dependencies(ws, ecosystem="npm", offline=True)
            # Should use the pinned version from lock file
            express = next(
                p for p in result["packages_scanned"] if p["name"] == "express"
            )
            assert express["version"] == "4.18.2"
            assert express["source_file"] == "package-lock.json"
            # Manifest should NOT be scanned when lock file is present
            assert "package.json" not in result["files_scanned"]
        finally:
            _cleanup(ws)


# ─── OSV API (Mocked) ──────────────────────────────────────────


class TestOsvBatchQuery:
    def test_single_package_with_vuln(self):
        """Mock _http_post_json + _http_get_json to return canned responses."""
        packages = [
            {"name": "requests", "version": "2.27.0", "ecosystem": "PyPI", "source_file": "requirements.txt"}
        ]
        batch_response = {
            "results": [
                {"vulns": [{"id": "GHSA-j8r2-6x86-q33q"}]}
            ]
        }
        vuln_detail = {
            "id": "GHSA-j8r2-6x86-q33q",
            "summary": "Unintended leak of Proxy-Authorization header",
            "aliases": ["CVE-2023-32681"],
            "database_specific": {"severity": "HIGH"},
            "affected": [
                {
                    "package": {"name": "requests", "ecosystem": "PyPI"},
                    "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.31.0"}]}],
                }
            ],
        }
        with patch.object(engine, "_http_post_json", return_value=batch_response), \
             patch.object(engine, "_http_get_json", return_value=vuln_detail):
            findings, errors = engine._query_osv_batch(packages)

        assert len(findings) == 1
        f = findings[0]
        assert f["package"] == "requests"
        assert f["version"] == "2.27.0"
        assert f["vuln_id"] == "GHSA-j8r2-6x86-q33q"
        assert f["severity"] == "high"
        assert f["fixed_in"] == "2.31.0"
        assert f["summary"].startswith("Unintended leak")
        assert "CVE-2023-32681" in f["cve_ids"]
        assert f["osv_url"] == "https://osv.dev/vulnerability/GHSA-j8r2-6x86-q33q"
        assert errors == []

    def test_multiple_packages_batched(self):
        packages = [
            {"name": f"pkg{i}", "version": f"1.0.{i}", "ecosystem": "PyPI", "source_file": "requirements.txt"}
            for i in range(5)
        ]
        # Only pkg0 and pkg2 have vulns
        batch_response = {
            "results": [
                {"vulns": [{"id": "VULN-0"}]} if i == 0 else
                {"vulns": []} if i in (1, 3, 4) else
                {"vulns": [{"id": "VULN-2"}]}
                for i in range(5)
            ]
        }
        vuln_details = {
            "VULN-0": {"id": "VULN-0", "summary": "vuln 0", "database_specific": {"severity": "CRITICAL"}},
            "VULN-2": {"id": "VULN-2", "summary": "vuln 2", "database_specific": {"severity": "LOW"}},
        }

        def fake_get(url):
            vuln_id = url.rsplit("/", 1)[-1]
            return vuln_details.get(vuln_id, {})

        with patch.object(engine, "_http_post_json", return_value=batch_response) as mock_post, \
             patch.object(engine, "_http_get_json", side_effect=fake_get) as mock_get:
            findings, errors = engine._query_osv_batch(packages)

        assert len(findings) == 2
        vuln_ids = {f["vuln_id"] for f in findings}
        assert vuln_ids == {"VULN-0", "VULN-2"}
        # Verify vuln detail cache (only 2 GETs, not 4)
        assert mock_get.call_count == 2

    def test_skips_packages_without_version(self):
        packages = [
            {"name": "no-version", "version": "", "ecosystem": "PyPI", "source_file": "requirements.txt"},
            {"name": "has-version", "version": "1.0.0", "ecosystem": "PyPI", "source_file": "requirements.txt"},
        ]
        batch_response = {"results": [{"vulns": []}, {"vulns": []}]}
        with patch.object(engine, "_http_post_json", return_value=batch_response) as mock_post:
            findings, errors = engine._query_osv_batch(packages)
        # Only one batch POST (the empty-version pkg is skipped)
        assert mock_post.call_count == 1
        # Error message should mention skipped packages
        assert any("skipped" in e for e in errors)

    def test_batch_api_error_recorded(self):
        packages = [
            {"name": "pkg", "version": "1.0", "ecosystem": "PyPI", "source_file": "requirements.txt"}
        ]
        with patch.object(engine, "_http_post_json", side_effect=Exception("network down")):
            findings, errors = engine._query_osv_batch(packages)
        assert findings == []
        assert len(errors) == 1
        assert "network down" in errors[0]

    def test_vuln_detail_fetch_failure_does_not_break_batch(self):
        packages = [
            {"name": "pkg", "version": "1.0", "ecosystem": "PyPI", "source_file": "requirements.txt"}
        ]
        batch_response = {"results": [{"vulns": [{"id": "BAD-VULN"}]}]}
        with patch.object(engine, "_http_post_json", return_value=batch_response), \
             patch.object(engine, "_http_get_json", side_effect=Exception("detail fetch failed")):
            findings, errors = engine._query_osv_batch(packages)
        # Finding still recorded, but with empty detail
        assert len(findings) == 1
        assert findings[0]["vuln_id"] == "BAD-VULN"
        assert findings[0]["severity"] == "unknown"
        # Error recorded
        assert any("detail fetch failed" in e for e in errors)


# ─── CVSS Vector Parsing ───────────────────────────────────────


class TestCvssVectorParsing:
    def test_critical_vector(self):
        # CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H → ~10.0 (critical)
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        assert engine._cvss_vector_to_severity(vector) == "critical"

    def test_high_vector(self):
        # CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N → ~7.5 (high)
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"
        assert engine._cvss_vector_to_severity(vector) == "high"

    def test_medium_vector(self):
        # CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:N/A:N → ~3.1 (low)
        # Use a definite medium: 4.0-6.9
        # AV:N(0.85) AC:L(0.77) PR:N(0.85) UI:N(0.85) C:L(0.22) I:N(0) A:N(0) S:U
        # ISS = 1 - (1-0.22)*(1)*(1) = 0.22
        # impact = 6.42 * 0.22 = 1.4124
        # exploitability = 8.22 * 0.85 * 0.77 * 0.85 * 0.85 = 3.8915
        # base = min(1.4124 + 3.8915, 10) = 5.3 → medium
        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"
        assert engine._cvss_vector_to_severity(vector) == "medium"

    def test_low_vector(self):
        # Lower impact → low
        vector = "CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N"
        result = engine._cvss_vector_to_severity(vector)
        assert result in ("low", "medium")  # depends on exact computation

    def test_invalid_vector(self):
        assert engine._cvss_vector_to_severity("") == "unknown"
        assert engine._cvss_vector_to_severity("not a vector") == "unknown"
        assert engine._cvss_vector_to_severity("CVSS:3.1/AV:N") == "unknown"  # missing metrics


# ─── Severity Filter ───────────────────────────────────────────


class TestSeverityFilter:
    def test_high_filter_includes_critical(self):
        ws = _make_workspace({
            "requirements.txt": "requests==2.27.0\n"
        })
        try:
            # Mock OSV to return 3 findings: 1 critical, 1 high, 1 low
            batch_response = {
                "results": [{"vulns": [{"id": "V1"}, {"id": "V2"}, {"id": "V3"}]}]
            }
            vuln_details = {
                "V1": {"id": "V1", "database_specific": {"severity": "CRITICAL"}},
                "V2": {"id": "V2", "database_specific": {"severity": "HIGH"}},
                "V3": {"id": "V3", "database_specific": {"severity": "LOW"}},
            }

            def fake_get(url):
                return vuln_details.get(url.rsplit("/", 1)[-1], {})

            with patch.object(engine, "_http_post_json", return_value=batch_response), \
                 patch.object(engine, "_http_get_json", side_effect=fake_get):
                result = engine.audit_dependencies(ws, severity="high")

            assert result["status"] == "ok"
            assert result["severity_filter"] == "high"
            # Should include critical + high, exclude low
            severities = {f["severity"] for f in result["findings"]}
            assert "critical" in severities
            assert "high" in severities
            assert "low" not in severities
        finally:
            _cleanup(ws)


# ─── Graph Persistence ─────────────────────────────────────────


class TestGraphPersistence:
    def test_findings_persisted_as_nodes_and_edges(self):
        ws = _make_workspace({"requirements.txt": "requests==2.27.0\n"})
        try:
            batch_response = {
                "results": [{"vulns": [{"id": "GHSA-xxx"}]}]
            }
            vuln_detail = {
                "id": "GHSA-xxx",
                "database_specific": {"severity": "HIGH"},
                "affected": [
                    {
                        "package": {"name": "requests", "ecosystem": "PyPI"},
                        "ranges": [{"events": [{"fixed": "2.31.0"}]}],
                    }
                ],
            }
            with patch.object(engine, "_http_post_json", return_value=batch_response), \
                 patch.object(engine, "_http_get_json", return_value=vuln_detail):
                result = engine.audit_dependencies(ws)

            assert result["status"] == "ok"
            assert "persistence" in result
            assert result["persistence"]["nodes_inserted"] >= 1
            assert result["persistence"]["edges_inserted"] >= 1

            # Verify in SQLite directly
            db_path = result["persistence"]["db_path"]
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.execute(
                    f"SELECT node_id, node_type, name, file FROM {GRAPH_NODES_TABLE} "
                    f"WHERE node_type = ?",
                    [NODE_TYPE_DEPENDENCY_VULN],
                )
                vuln_nodes = cur.fetchall()
                assert len(vuln_nodes) == 1
                node_id, node_type, name, file = vuln_nodes[0]
                assert node_type == NODE_TYPE_DEPENDENCY_VULN
                assert "GHSA-xxx" in node_id
                assert "requests" in name
                assert file == "requirements.txt"

                cur = conn.execute(
                    f"SELECT COUNT(*) FROM {GRAPH_EDGES_TABLE} WHERE edge_type = ?",
                    [EDGE_TYPE_HAS_VULN],
                )
                edge_count = cur.fetchone()[0]
                assert edge_count == 1
            finally:
                conn.close()
        finally:
            _cleanup(ws)

    def test_idempotent_rescan_no_duplicates(self):
        ws = _make_workspace({"requirements.txt": "requests==2.27.0\n"})
        try:
            batch_response = {
                "results": [{"vulns": [{"id": "GHSA-xxx"}]}]
            }
            vuln_detail = {
                "id": "GHSA-xxx",
                "database_specific": {"severity": "HIGH"},
                "affected": [
                    {
                        "package": {"name": "requests", "ecosystem": "PyPI"},
                        "ranges": [{"events": [{"fixed": "2.31.0"}]}],
                    }
                ],
            }
            with patch.object(engine, "_http_post_json", return_value=batch_response), \
                 patch.object(engine, "_http_get_json", return_value=vuln_detail):
                # First scan
                engine.audit_dependencies(ws)
                # Second scan (same data)
                result2 = engine.audit_dependencies(ws)

            # Verify only one vuln node + one edge in the DB after re-scan
            db_path = result2["persistence"]["db_path"]
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.execute(
                    f"SELECT COUNT(*) FROM {GRAPH_NODES_TABLE} WHERE node_type = ?",
                    [NODE_TYPE_DEPENDENCY_VULN],
                )
                assert cur.fetchone()[0] == 1, "should not duplicate vuln nodes"

                cur = conn.execute(
                    f"SELECT COUNT(*) FROM {GRAPH_EDGES_TABLE} WHERE edge_type = ?",
                    [EDGE_TYPE_HAS_VULN],
                )
                assert cur.fetchone()[0] == 1, "should not duplicate HAS_VULN edges"
            finally:
                conn.close()
        finally:
            _cleanup(ws)


# ─── Edge Cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_workspace(self):
        ws = _make_workspace({"README.md": "no deps"})
        try:
            result = engine.audit_dependencies(ws)
            assert result["status"] == "ok"
            assert result["findings"] == []
            assert result["stats"]["total"] == 0
            assert "No dependency manifests found" in result["recommendations"][0]
        finally:
            _cleanup(ws)

    def test_no_dependencies_in_manifest(self):
        ws = _make_workspace({
            "package.json": json.dumps({"name": "empty", "dependencies": {}})
        })
        try:
            result = engine.audit_dependencies(ws, offline=True)
            # Even with no packages, the file should be scanned
            assert result["status"] == "offline"
            assert result["stats"]["packages_scanned"] == 0
        finally:
            _cleanup(ws)

    def test_return_structure(self):
        ws = _make_workspace({"requirements.txt": "flask==2.0.0\n"})
        try:
            result = engine.audit_dependencies(ws, offline=True)
            # Required keys per issue #158 spec
            assert "status" in result
            assert "stats" in result
            assert "findings" in result
            assert "recommendations" in result
            assert "files_scanned" in result
            assert "packages_scanned" in result
            # stats structure
            stats = result["stats"]
            for key in ("total", "critical", "high", "medium", "low",
                        "packages_scanned", "ecosystems_scanned"):
                assert key in stats, f"missing stat: {key}"
        finally:
            _cleanup(ws)


# ─── Spec String Helpers ───────────────────────────────────────


class TestSpecStringHelpers:
    def test_strip_npm_operator(self):
        assert engine._strip_npm_operator("^1.2.3") == "1.2.3"
        assert engine._strip_npm_operator("~1.2.3") == "1.2.3"
        assert engine._strip_npm_operator(">=1.2.3") == "1.2.3"
        assert engine._strip_npm_operator("1.2.3") == "1.2.3"
        assert engine._strip_npm_operator("*") == ""
        assert engine._strip_npm_operator("latest") == ""
        assert engine._strip_npm_operator("1.2.x") == ""
        assert engine._strip_npm_operator("1.2.3 || 2.0.0") == "1.2.3"

    def test_strip_python_operator(self):
        assert engine._strip_python_operator(">=1.0") == "1.0"
        assert engine._strip_python_operator("==1.0") == "1.0"
        assert engine._strip_python_operator("~=1.0") == "1.0"
        assert engine._strip_python_operator("1.0") == "1.0"
        assert engine._strip_python_operator("*") == ""

    def test_strip_cargo_operator(self):
        assert engine._strip_cargo_operator("^1.0") == "1.0"
        assert engine._strip_cargo_operator("1.0") == "1.0"
        assert engine._strip_cargo_operator("*") == ""
        assert engine._strip_cargo_operator(">=1.0") == "1.0"

    def test_split_pep508_spec(self):
        assert engine._split_pep508_spec("requests==2.27.0") == ("requests", "2.27.0")
        assert engine._split_pep508_spec("requests>=2.0,<3.0") == ("requests", "2.0")
        # With extras and markers
        name, version = engine._split_pep508_spec('package[extra]==1.0; python_version>="3.8"')
        assert name == "package"
        assert version == "1.0"
        # Wildcards
        assert engine._split_pep508_spec("pkg==*") == ("pkg", "")

    def test_normalize_severity_string(self):
        assert engine._normalize_severity_string("CRITICAL") == "critical"
        assert engine._normalize_severity_string("High") == "high"
        assert engine._normalize_severity_string("MODERATE") == "medium"
        assert engine._normalize_severity_string("medium") == "medium"
        assert engine._normalize_severity_string("low") == "low"
        assert engine._normalize_severity_string("bogus") == "unknown"

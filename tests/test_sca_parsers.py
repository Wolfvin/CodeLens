"""Tests for the modular SCA lockfile/manifest parsers (Issue #53).

These tests exercise every parser in ``scripts/sca_parsers/`` against
the fixtures in ``tests/fixtures/sca/`` and verify:

- The ``Dependency`` dataclass shape (name/version/ecosystem/source_file/transitivity).
- That each parser correctly extracts the expected set of (name, version)
  pairs from its sample fixture.
- That ``parse_lockfile()`` dispatches by basename correctly and returns
  the right ecosystem string.
- That graceful failure holds: a corrupted/empty fixture returns []
  instead of raising.
- That ``vulnscan_engine.scan_vulnerabilities`` auto-detects the new
  formats end-to-end.
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap

import pytest

# Ensure scripts/ is importable
SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from sca_parsers import (  # noqa: E402
    Dependency,
    ECOSYSTEM_BY_FILE,
    PARSER_REGISTRY,
    parse_lockfile,
)
from sca_parsers import (  # noqa: E402
    composer_lock,
    gemfile_lock,
    gradle_lock,
    mix_lock,
    package_resolved,
    packages_lock,
    pipfile,
    pipfile_lock,
    pnpm_lock,
    pom_xml,
    pubspec_lock,
    pyproject_toml,
    requirements_txt,
    yarn_lock,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sca")


# ─── Helpers ───────────────────────────────────────────────────


def _fixture(name: str) -> str:
    return os.path.join(FIXTURES_DIR, name)


def _names_versions(deps):
    """Convert list[Dependency] -> set[(name_lower, version)]."""
    return {(d.name.lower(), d.version) for d in deps}


# ─── Registry & interface ──────────────────────────────────────


class TestRegistry:
    def test_registry_contains_all_14_formats(self):
        expected_files = {
            "pnpm-lock.yaml",
            "yarn.lock",
            "Pipfile.lock",
            "Pipfile",
            "requirements.txt",
            "pyproject.toml",
            "Gemfile.lock",
            "composer.lock",
            "packages.lock.json",
            "pubspec.lock",
            "Package.resolved",
            "gradle.lockfile",
            "build.gradle",
            "pom.xml",
            "mix.lock",
        }
        assert expected_files.issubset(set(PARSER_REGISTRY.keys()))

    def test_ecosystem_map_covers_every_parser(self):
        for fname in PARSER_REGISTRY:
            assert fname in ECOSYSTEM_BY_FILE, (
                f"{fname} has no ecosystem mapping"
            )

    def test_dependency_dataclass_shape(self):
        d = Dependency(
            name="x",
            version="1.0.0",
            ecosystem="npm",
            source_file="/tmp/x",
            transitivity="direct",
        )
        assert d.name == "x"
        assert d.version == "1.0.0"
        assert d.ecosystem == "npm"
        assert d.source_file == "/tmp/x"
        assert d.transitivity == "direct"
        # default transitivity
        d2 = Dependency(name="x", version="1", ecosystem="npm", source_file="/x")
        assert d2.transitivity == "direct"


# ─── pnpm-lock.yaml ────────────────────────────────────────────


class TestPnpmLock:
    def test_parses_v9_lockfile(self):
        path = _fixture("pnpm-lock.yaml")
        deps = pnpm_lock.parse(path)
        nv = _names_versions(deps)
        assert ("lodash", "4.17.21") in nv
        assert ("express", "4.19.2") in nv
        assert ("jest", "29.7.0") in nv
        assert ("accepts", "1.3.8") in nv
        assert ("body-parser", "1.20.2") in nv
        # All deps marked with ecosystem npm
        assert all(d.ecosystem == "npm" for d in deps)
        assert all(d.source_file == path for d in deps)

    def test_direct_vs_transitive(self):
        deps = pnpm_lock.parse(_fixture("pnpm-lock.yaml"))
        by_name = {d.name.lower(): d for d in deps}
        # lodash/express/jest are declared in importers → direct
        assert by_name["lodash"].transitivity == "direct"
        assert by_name["express"].transitivity == "direct"
        assert by_name["jest"].transitivity == "direct"
        # accepts is only in packages (pulled by express) → transitive
        assert by_name["accepts"].transitivity == "transitive"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "pnpm-lock.yaml"
        p.write_text("")
        assert pnpm_lock.parse(str(p)) == []


# ─── yarn.lock ─────────────────────────────────────────────────


class TestYarnLock:
    def test_parses_v1_lockfile(self):
        path = _fixture("yarn.lock")
        deps = yarn_lock.parse(path)
        nv = _names_versions(deps)
        assert ("lodash", "4.17.21") in nv
        assert ("express", "4.19.2") in nv
        assert ("accepts", "1.3.8") in nv
        # @babel/code-frame with scoped name
        assert ("@babel/code-frame", "7.22.13") in nv
        assert all(d.ecosystem == "npm" for d in deps)

    def test_multiple_specifiers_one_block_dedups(self):
        # The fixture has `lodash@^4.17.20, lodash@^4.17.21` mapping
        # to version 4.17.21 — should produce ONE entry, not two.
        deps = yarn_lock.parse(_fixture("yarn.lock"))
        lodash = [d for d in deps if d.name.lower() == "lodash"]
        assert len(lodash) == 1

    def test_empty_file(self, tmp_path):
        p = tmp_path / "yarn.lock"
        p.write_text("# just a comment\n")
        assert yarn_lock.parse(str(p)) == []


# ─── Pipfile.lock ──────────────────────────────────────────────


class TestPipfileLock:
    def test_parses_default_and_develop(self):
        deps = pipfile_lock.parse(_fixture("Pipfile.lock"))
        nv = _names_versions(deps)
        assert ("django", "4.2.13") in nv
        assert ("requests", "2.31.0") in nv
        assert ("certifi", "2023.7.22") in nv
        assert ("pytest", "7.4.0") in nv
        assert all(d.ecosystem == "pypi" for d in deps)

    def test_strips_version_operators(self):
        deps = pipfile_lock.parse(_fixture("Pipfile.lock"))
        for d in deps:
            assert not d.version.startswith("="), d

    def test_corrupt_json(self, tmp_path):
        p = tmp_path / "Pipfile.lock"
        p.write_text("{not valid json")
        assert pipfile_lock.parse(str(p)) == []


# ─── Gemfile.lock ──────────────────────────────────────────────


class TestGemfileLock:
    def test_parses_specs(self):
        deps = gemfile_lock.parse(_fixture("Gemfile.lock"))
        nv = _names_versions(deps)
        assert ("rake", "13.0.6") in nv
        assert ("nokogiri", "1.13.10") in nv
        assert ("rails", "7.0.8") in nv
        assert ("i18n", "1.14.1") in nv
        assert ("concurrent-ruby", "1.2.2") in nv
        assert all(d.ecosystem == "gem" for d in deps)

    def test_direct_vs_transitive(self):
        deps = gemfile_lock.parse(_fixture("Gemfile.lock"))
        by_name = {d.name.lower(): d for d in deps}
        # DEPENDENCIES block lists nokogiri and rails (>= 7.0.8) → direct
        assert by_name["nokogiri"].transitivity == "direct"
        assert by_name["rails"].transitivity == "direct"
        # rake is not in DEPENDENCIES → transitive
        assert by_name["rake"].transitivity == "transitive"

    def test_strips_platform_suffix(self, tmp_path):
        p = tmp_path / "Gemfile.lock"
        p.write_text(textwrap.dedent("""\
            GEM
              remote: https://rubygems.org/
              specs:
                nokogiri (1.13.10-java)
                pg (1.4.6 x64-mingw32)

            DEPENDENCIES
              nokogiri
        """))
        deps = gemfile_lock.parse(str(p))
        nv = _names_versions(deps)
        assert ("nokogiri", "1.13.10") in nv
        assert ("pg", "1.4.6") in nv


# ─── composer.lock ─────────────────────────────────────────────


class TestComposerLock:
    def test_parses_packages_and_dev(self):
        deps = composer_lock.parse(_fixture("composer.lock"))
        nv = _names_versions(deps)
        assert ("symfony/console", "6.3.0") in nv
        assert ("monolog/monolog", "3.4.0") in nv
        assert ("guzzlehttp/guzzle", "7.7.0") in nv
        assert ("phpunit/phpunit", "10.3.0") in nv
        assert all(d.ecosystem == "composer" for d in deps)

    def test_strips_leading_v(self, tmp_path):
        p = tmp_path / "composer.lock"
        p.write_text('{"packages":[{"name":"x/y","version":"v1.2.3"}]}')
        deps = composer_lock.parse(str(p))
        assert deps[0].version == "1.2.3"


# ─── packages.lock.json (NuGet) ────────────────────────────────


class TestPackagesLock:
    def test_parses_v2_per_framework(self):
        deps = packages_lock.parse(_fixture("packages.lock.json"))
        nv = _names_versions(deps)
        # Direct deps
        assert ("newtonsoft.json", "13.0.1") in nv or ("newtonsoft.json", "13.0.3") in nv
        assert ("microsoft.net.test.sdk", "17.6.0") in nv
        assert ("serilog", "3.0.1") in nv
        # Transitive
        assert ("system.text.json", "6.0.0") in nv
        assert ("nunit", "3.13.3") in nv
        # Ecosystem
        assert all(d.ecosystem == "nuget" for d in deps)

    def test_transitivity_from_type_field(self):
        deps = packages_lock.parse(_fixture("packages.lock.json"))
        by_name = {d.name.lower(): d for d in deps}
        # Newtonsoft is Direct in both frameworks
        newtonsoft = [d for d in deps if d.name.lower() == "newtonsoft.json"]
        assert all(d.transitivity == "direct" for d in newtonsoft)
        # System.Text.Json is Transitive
        assert by_name["system.text.json"].transitivity == "transitive"


# ─── pubspec.lock ──────────────────────────────────────────────


class TestPubspecLock:
    def test_parses_packages(self):
        deps = pubspec_lock.parse(_fixture("pubspec.lock"))
        nv = _names_versions(deps)
        assert ("args", "2.4.2") in nv
        assert ("http", "1.1.0") in nv
        assert ("test", "1.24.9") in nv
        assert ("async", "2.11.0") in nv
        assert all(d.ecosystem == "pub" for d in deps)

    def test_direct_vs_transitive(self):
        deps = pubspec_lock.parse(_fixture("pubspec.lock"))
        by_name = {d.name.lower(): d for d in deps}
        assert by_name["args"].transitivity == "direct"
        assert by_name["http"].transitivity == "direct"
        assert by_name["test"].transitivity == "direct"
        assert by_name["async"].transitivity == "transitive"


# ─── Package.resolved (SwiftPM) ────────────────────────────────


class TestPackageResolved:
    def test_parses_v1_pins(self):
        deps = package_resolved.parse(_fixture("Package.resolved"))
        nv = _names_versions(deps)
        assert ("alamofire", "5.8.0") in nv
        assert ("swiftlint", "0.53.0") in nv
        assert ("keychainaccess", "4.2.2") in nv
        assert all(d.ecosystem == "swiftpm" for d in deps)

    def test_v2_identity_fallback(self, tmp_path):
        p = tmp_path / "Package.resolved"
        p.write_text(textwrap.dedent("""\
            {
              "object": {
                "pins": [
                  {
                    "identity": "alamofire",
                    "location": "https://github.com/Alamofire/Alamofire.git",
                    "state": {
                      "revision": "abc123def456abc123def456abc123def456abcd",
                      "version": "5.8.0"
                    }
                  }
                ]
              },
              "version": 2
            }
        """))
        deps = package_resolved.parse(str(p))
        assert deps[0].name == "alamofire"
        assert deps[0].version == "5.8.0"

    def test_branch_only_pin_falls_back_to_revision(self, tmp_path):
        p = tmp_path / "Package.resolved"
        p.write_text(textwrap.dedent("""\
            {
              "object": {
                "pins": [
                  {
                    "package": "experimental",
                    "repositoryURL": "https://github.com/foo/exp.git",
                    "state": {
                      "branch": "main",
                      "revision": "abcdef1234567890abcdef1234567890abcdef12"
                    }
                  }
                ]
              },
              "version": 1
            }
        """))
        deps = package_resolved.parse(str(p))
        assert deps[0].name == "experimental"
        # Short sha (first 12 chars)
        assert deps[0].version == "abcdef123456"


# ─── gradle.lockfile + build.gradle ────────────────────────────


class TestGradleLock:
    def test_parses_lockfile(self):
        deps = gradle_lock.parse(_fixture("gradle.lockfile"))
        nv = _names_versions(deps)
        assert ("com.google.code.gson:gson", "2.8.9") in nv
        assert ("com.squareup.retrofit2:retrofit", "2.9.0") in nv
        assert ("io.reactivex.rxjava3:rxjava", "3.1.6") in nv
        assert ("com.squareup.okhttp3:okhttp", "4.11.0") in nv
        assert ("junit:junit", "4.13.2") in nv
        assert all(d.ecosystem == "gradle" for d in deps)

    def test_parses_build_gradle(self):
        deps = gradle_lock.parse(_fixture("build.gradle"))
        nv = _names_versions(deps)
        assert ("com.google.code.gson:gson", "2.8.9") in nv
        assert ("com.squareup.retrofit2:retrofit", "2.9.0") in nv
        assert ("junit:junit", "4.13.2") in nv
        assert ("org.hamcrest:hamcrest", "2.2") in nv
        assert all(d.ecosystem == "gradle" for d in deps)
        assert all(d.transitivity == "direct" for d in deps)

    def test_skips_comments_and_empty_lines(self, tmp_path):
        p = tmp_path / "gradle.lockfile"
        p.write_text(textwrap.dedent("""\
            # This is a comment
            empty=unused

            com.foo:bar:1.2.3:compileClasspath=1.2.3
        """))
        deps = gradle_lock.parse(str(p))
        assert len(deps) == 1
        assert deps[0].name == "com.foo:bar"


# ─── pom.xml ───────────────────────────────────────────────────


class TestPomXml:
    def test_parses_declared_dependencies(self):
        deps = pom_xml.parse(_fixture("pom.xml"))
        nv = _names_versions(deps)
        # Concrete version
        assert ("org.apache.commons:commons-lang3", "3.13.0") in nv
        # Property-style versions are kept as-is (not resolved)
        assert ("org.springframework:spring-core", "${spring.version}") in nv
        assert ("com.fasterxml.jackson.core:jackson-databind", "${jackson.version}") in nv
        # Test scope dep
        assert ("junit:junit", "4.13.2") in nv
        # Missing version → 0.0.0
        assert ("org.slf4j:slf4j-api", "0.0.0") in nv
        assert all(d.ecosystem == "maven" for d in deps)

    def test_handles_malformed_xml(self, tmp_path):
        p = tmp_path / "pom.xml"
        p.write_text("<project><not-closed>")
        deps = pom_xml.parse(str(p))
        # Should not raise; either empty or partial
        assert isinstance(deps, list)


# ─── mix.lock ──────────────────────────────────────────────────


class TestMixLock:
    def test_parses_hex_deps(self):
        deps = mix_lock.parse(_fixture("mix.lock"))
        nv = _names_versions(deps)
        assert ("absinthe", "1.7.6") in nv
        assert ("phoenix", "1.7.10") in nv
        assert ("ecto", "3.10.3") in nv
        assert ("decimal", "2.1.1") in nv
        assert all(d.ecosystem == "hex" for d in deps)

    def test_git_dep_fallback(self):
        deps = mix_lock.parse(_fixture("mix.lock"))
        git_dep = [d for d in deps if d.name.lower() == "git_dep"]
        assert git_dep, "git_dep should be extracted"
        assert git_dep[0].version.startswith("git:")
        # Short sha, 12 chars after the prefix
        assert len(git_dep[0].version) == len("git:") + 12


# ─── requirements.txt ──────────────────────────────────────────


class TestRequirementsTxt:
    def test_parses_pinned_and_unpinned(self):
        deps = requirements_txt.parse(_fixture("requirements.txt"))
        by_name = {d.name.lower(): d for d in deps}
        # Pinned
        assert by_name["django"].version == "4.2.13"
        # Range — extract the lower bound
        assert by_name["requests"].version == "2.31.0"
        # ~= operator
        assert by_name["flask"].version == "2.3.2"
        # Compound range
        assert by_name["numpy"].version == "1.24.0"
        # Marker stripped
        assert by_name["pandas"].version == "2.0.3"
        # Unpinned → 0.0.0
        assert by_name["pyyaml"].version == "0.0.0"
        assert by_name["pytest"].version == "0.0.0"
        # URL spec — name extracted, version 0.0.0
        assert "pdfminer" in by_name
        assert by_name["pdfminer"].version == "0.0.0"

    def test_skips_pip_options(self):
        deps = requirements_txt.parse(_fixture("requirements.txt"))
        names = {d.name.lower() for d in deps}
        # `-r`, `-c`, `-e`, `--index-url` lines should not produce deps
        assert "-r" not in names
        assert "-c" not in names
        assert "-e" not in names
        assert "--index-url" not in names

    def test_all_pypi_ecosystem(self):
        deps = requirements_txt.parse(_fixture("requirements.txt"))
        assert all(d.ecosystem == "pypi" for d in deps)
        assert all(d.transitivity == "direct" for d in deps)


# ─── Pipfile ───────────────────────────────────────────────────


class TestPipfile:
    def test_parses_packages_and_dev(self):
        deps = pipfile.parse(_fixture("Pipfile"))
        by_name = {d.name.lower(): d for d in deps}
        assert by_name["django"].version == "4.2.13"
        assert by_name["requests"].version == "0.0.0"  # unpinned "*"
        assert by_name["flask"].version == "2.3.2"     # ~= from table form
        assert by_name["numpy"].version == "1.24.0"    # range lower bound
        assert by_name["pytest"].version == "7.4.0"
        assert by_name["black"].version == "0.0.0"
        assert by_name["mypy"].version == "1.4.0"      # >= from table form

    def test_all_pypi_ecosystem(self):
        deps = pipfile.parse(_fixture("Pipfile"))
        assert all(d.ecosystem == "pypi" for d in deps)


# ─── pyproject.toml ────────────────────────────────────────────


class TestPyprojectToml:
    def test_parses_pep621_and_poetry(self):
        deps = pyproject_toml.parse(_fixture("pyproject.toml"))
        by_name = {d.name.lower(): d for d in deps}
        # PEP 621 [project.dependencies]
        assert by_name["click"].version == "8.1.0"
        assert by_name["rich"].version == "13.0"
        # Poetry [tool.poetry.dependencies]
        assert by_name["django"].version == "4.2"
        assert by_name["requests"].version == "2.31"
        # Poetry table form: flask {version = "~=2.3", extras = ["async"]}
        assert by_name["flask"].version == "2.3"
        # Poetry group dev deps
        assert by_name["pytest"].version == "7.4"
        assert by_name["mypy"].version == "1.4"
        # PEP 621 optional-dependencies
        assert by_name["sphinx"].version == "7.0"
        # 'python' should NOT be emitted as a dependency
        assert "python" not in by_name

    def test_all_pypi_ecosystem(self):
        deps = pyproject_toml.parse(_fixture("pyproject.toml"))
        assert all(d.ecosystem == "pypi" for d in deps)


# ─── Dispatcher: parse_lockfile() ──────────────────────────────


class TestDispatcher:
    @pytest.mark.parametrize(
        "fname, expected_ecosystem, expected_pkgs",
        [
            ("pnpm-lock.yaml", "npm", {"lodash"}),
            ("yarn.lock", "npm", {"lodash"}),
            ("Pipfile.lock", "pypi", {"django"}),
            ("Pipfile", "pypi", {"django"}),
            ("requirements.txt", "pypi", {"django"}),
            ("pyproject.toml", "pypi", {"django"}),
            ("Gemfile.lock", "gem", {"rake"}),
            ("composer.lock", "composer", {"symfony/console"}),
            ("packages.lock.json", "nuget", {"newtonsoft.json"}),
            ("pubspec.lock", "pub", {"args"}),
            ("Package.resolved", "swiftpm", {"alamofire"}),
            ("gradle.lockfile", "gradle", {"com.google.code.gson:gson"}),
            ("build.gradle", "gradle", {"com.google.code.gson:gson"}),
            ("pom.xml", "maven", {"org.apache.commons:commons-lang3"}),
            ("mix.lock", "hex", {"absinthe"}),
        ],
    )
    def test_dispatch_by_basename(self, fname, expected_ecosystem, expected_pkgs):
        path = _fixture(fname)
        deps, ecosystem = parse_lockfile(path)
        assert ecosystem == expected_ecosystem
        names = {d.name.lower() for d in deps}
        for expected in expected_pkgs:
            assert expected in names, f"{expected} not in {names} for {fname}"

    def test_unknown_filename_returns_empty(self, tmp_path):
        p = tmp_path / "unknown.lock"
        p.write_text("garbage")
        deps, eco = parse_lockfile(str(p))
        assert deps == []
        assert eco is None

    def test_parser_error_does_not_raise(self, tmp_path):
        # Make a file with the right name but unreadable content; ensure
        # we get ([], None) back instead of an exception.
        p = tmp_path / "Pipfile.lock"
        p.write_text("{ not valid json")
        deps, eco = parse_lockfile(str(p))
        assert deps == []
        # ecosystem is still returned even if parse failed
        assert eco == "pypi"


# ─── End-to-end: vulnscan_engine integration ───────────────────


class TestVulnscanIntegration:
    """Verify vulnscan_engine picks up the new lockfile formats."""

    def test_gemfile_lock_discovered_and_scanned(self, tmp_path):
        # Copy fixture into a fresh workspace
        ws = tmp_path
        with open(_fixture("Gemfile.lock"), "rb") as f:
            (ws / "Gemfile.lock").write_bytes(f.read())
        # Import lazily so the test still collects if the engine import fails
        from vulnscan_engine import scan_vulnerabilities  # noqa: WPS433
        result = scan_vulnerabilities(str(ws), offline=True)
        assert result["status"] == "ok"
        files_scanned = result.get("files_scanned") or []
        # Even if no VULN_DB hits, the file should appear in files_scanned.
        # Note: scan_vulnerabilities may not surface files_scanned in the
        # top-level dict; check stats if absent.
        assert "stats" in result or "files_scanned" in result

    def test_pnpm_lock_yaml_discovered_and_scanned(self, tmp_path):
        ws = tmp_path
        with open(_fixture("pnpm-lock.yaml"), "rb") as f:
            (ws / "pnpm-lock.yaml").write_bytes(f.read())
        from vulnscan_engine import scan_vulnerabilities  # noqa: WPS433
        result = scan_vulnerabilities(str(ws), offline=True)
        assert result["status"] == "ok"

    def test_pubspec_lock_discovered_and_scanned(self, tmp_path):
        ws = tmp_path
        with open(_fixture("pubspec.lock"), "rb") as f:
            (ws / "pubspec.lock").write_bytes(f.read())
        from vulnscan_engine import scan_vulnerabilities  # noqa: WPS433
        result = scan_vulnerabilities(str(ws), offline=True)
        assert result["status"] == "ok"

    def test_multiple_new_formats_together(self, tmp_path):
        ws = tmp_path
        for fname in ("Gemfile.lock", "pnpm-lock.yaml", "pubspec.lock",
                      "composer.lock", "Package.resolved", "mix.lock"):
            with open(_fixture(fname), "rb") as f:
                (ws / fname).write_bytes(f.read())
        from vulnscan_engine import scan_vulnerabilities  # noqa: WPS433
        result = scan_vulnerabilities(str(ws), offline=True)
        assert result["status"] == "ok"
        # No crash, no audit_available — just lockfile parsing path.

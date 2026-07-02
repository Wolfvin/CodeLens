# @WHO:   scripts/orient_lib/framework_db.py
# @WHAT:  Data-driven framework detection — ecosystem lookup table
# @PART:  orient
# @ENTRY: detect_frameworks_brief()

"""
Framework detection for the ``codelens orient`` command.

Lives in the ``orient_lib`` sub-package (not ``orient``) to avoid a Python
import collision with ``scripts/commands/orient.py``.

Data-driven lookup table: each framework is defined by the package keys
that signal its presence in a manifest file (``package.json``,
``pyproject.toml``, ``requirements.txt``, ``go.mod``, ``Cargo.toml``,
``pom.xml`` / ``build.gradle``). Adding a new framework = one entry in
the ``ECOSYSTEM_FRAMEWORKS`` table — no code changes elsewhere.

The detector reads manifest files from the filesystem only (no
subprocess, no network). It returns a structured brief matching the
``orient`` output schema:

    {
        "ecosystem": "Node.js",
        "primary": "Next.js",
        "secondary": ["Prisma", "TailwindCSS", "Jest"],
        "summary": "Full-stack React app with ORM and CSS framework"
    }

Reference: issue #160, ported from codeglance's framework-detector.ts
(rewritten in Python idioms, no code copied).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["ECOSYSTEM_FRAMEWORKS", "detect_frameworks_brief"]

_logger = logging.getLogger("codelens.orient.framework_db")


# ─── Framework Lookup Table ────────────────────────────────────
#
# Each entry maps a framework name to the package keys that signal it.
# The ``ecosystem`` groups frameworks so the detector can report a
# single primary ecosystem. ``priority`` controls which framework is
# reported as ``primary`` when multiple are present (higher = primary).
#
# Adding a new framework: add one entry here. No other code changes.

ECOSYSTEM_FRAMEWORKS: Dict[str, List[Dict[str, Any]]] = {
    "Node.js": [
        {"name": "Next.js", "packages": ["next"], "priority": 100,
         "summary": "Full-stack React framework with SSR/SSG"},
        {"name": "Remix", "packages": ["@remix-run/react"], "priority": 100,
         "summary": "Full-stack React framework with nested routing"},
        {"name": "Nuxt", "packages": ["nuxt"], "priority": 100,
         "summary": "Full-stack Vue framework"},
        {"name": "Gatsby", "packages": ["gatsby"], "priority": 95,
         "summary": "Static site generator (React)"},
        {"name": "React", "packages": ["react", "react-dom"], "priority": 80,
         "summary": "UI library (React)"},
        {"name": "Vue", "packages": ["vue"], "priority": 80,
         "summary": "UI library (Vue)"},
        {"name": "Svelte", "packages": ["svelte"], "priority": 80,
         "summary": "UI compiler (Svelte)"},
        {"name": "Angular", "packages": ["@angular/core"], "priority": 90,
         "summary": "Full-stack SPA framework (Angular)"},
        {"name": "Express", "packages": ["express"], "priority": 70,
         "summary": "Node.js web server"},
        {"name": "Fastify", "packages": ["fastify"], "priority": 70,
         "summary": "Node.js web server (Fastify)"},
        {"name": "NestJS", "packages": ["@nestjs/core"], "priority": 85,
         "summary": "Node.js enterprise framework (NestJS)"},
        {"name": "Koa", "packages": ["koa"], "priority": 65,
         "summary": "Node.js web server (Koa)"},
        {"name": "Hono", "packages": ["hono"], "priority": 65,
         "summary": "Edge-first web framework (Hono)"},
        {"name": "Prisma", "packages": ["prisma", "@prisma/client"], "priority": 50,
         "summary": "TypeScript ORM (Prisma)"},
        {"name": "TypeORM", "packages": ["typeorm"], "priority": 45,
         "summary": "TypeScript ORM (TypeORM)"},
        {"name": "TailwindCSS", "packages": ["tailwindcss"], "priority": 40,
         "summary": "Utility-first CSS framework"},
        {"name": "Jest", "packages": ["jest"], "priority": 30,
         "summary": "JavaScript test runner"},
        {"name": "Vitest", "packages": ["vitest"], "priority": 30,
         "summary": "Vite-native test runner"},
        {"name": "Playwright", "packages": ["@playwright/test"], "priority": 30,
         "summary": "E2E browser test framework"},
        {"name": "Vite", "packages": ["vite"], "priority": 35,
         "summary": "Frontend build tool / dev server"},
        {"name": "Webpack", "packages": ["webpack"], "priority": 25,
         "summary": "Module bundler"},
        {"name": "ESLint", "packages": ["eslint"], "priority": 20,
         "summary": "JavaScript linter"},
        {"name": "Electron", "packages": ["electron"], "priority": 75,
         "summary": "Desktop app framework (Electron)"},
    ],
    "Python": [
        {"name": "FastAPI", "packages": ["fastapi"], "priority": 90,
         "summary": "Async web API framework (FastAPI)"},
        {"name": "Flask", "packages": ["flask"], "priority": 80,
         "summary": "Lightweight web framework (Flask)"},
        {"name": "Django", "packages": ["django"], "priority": 95,
         "summary": "Batteries-included web framework (Django)"},
        {"name": "Pyramid", "packages": ["pyramid"], "priority": 70,
         "summary": "Web framework (Pyramid)"},
        {"name": "Tornado", "packages": ["tornado"], "priority": 70,
         "summary": "Async web framework (Tornado)"},
        {"name": "Sanic", "packages": ["sanic"], "priority": 75,
         "summary": "Fast async web framework (Sanic)"},
        {"name": "Starlette", "packages": ["starlette"], "priority": 60,
         "summary": "Lightweight ASGI framework (Starlette)"},
        {"name": "Aiohttp", "packages": ["aiohttp"], "priority": 65,
         "summary": "Async HTTP client/server (aiohttp)"},
        {"name": "Pydantic", "packages": ["pydantic"], "priority": 40,
         "summary": "Data validation (Pydantic)"},
        {"name": "SQLAlchemy", "packages": ["sqlalchemy"], "priority": 45,
         "summary": "Python ORM (SQLAlchemy)"},
        {"name": "Tortoise ORM", "packages": ["tortoise-orm"], "priority": 40,
         "summary": "Async ORM (Tortoise)"},
        {"name": "Celery", "packages": ["celery"], "priority": 55,
         "summary": "Distributed task queue (Celery)"},
        {"name": "pytest", "packages": ["pytest"], "priority": 30,
         "summary": "Python test runner"},
        {"name": "NumPy", "packages": ["numpy"], "priority": 35,
         "summary": "Numerical computing (NumPy)"},
        {"name": "Pandas", "packages": ["pandas"], "priority": 35,
         "summary": "Data analysis (Pandas)"},
        {"name": "Scikit-learn", "packages": ["scikit-learn"], "priority": 50,
         "summary": "Machine learning (scikit-learn)"},
        {"name": "PyTorch", "packages": ["torch"], "priority": 55,
         "summary": "Deep learning (PyTorch)"},
        {"name": "TensorFlow", "packages": ["tensorflow"], "priority": 55,
         "summary": "Deep learning (TensorFlow)"},
        {"name": "LangChain", "packages": ["langchain"], "priority": 60,
         "summary": "LLM application framework (LangChain)"},
    ],
    "Go": [
        {"name": "Gin", "packages": ["github.com/gin-gonic/gin"], "priority": 85,
         "summary": "HTTP web framework (Gin)"},
        {"name": "Echo", "packages": ["github.com/labstack/echo"], "priority": 80,
         "summary": "HTTP web framework (Echo)"},
        {"name": "Fiber", "packages": ["github.com/gofiber/fiber"], "priority": 80,
         "summary": "Express-inspired web framework (Fiber)"},
        {"name": "Chi", "packages": ["github.com/go-chi/chi"], "priority": 75,
         "summary": "Lightweight HTTP router (Chi)"},
        {"name": "GORM", "packages": ["gorm.io/gorm"], "priority": 50,
         "summary": "Go ORM (GORM)"},
        {"name": "sqlx", "packages": ["github.com/jmoiron/sqlx"], "priority": 40,
         "summary": "SQL extensions (sqlx)"},
        {"name": "Cobra", "packages": ["github.com/spf13/cobra"], "priority": 60,
         "summary": "CLI framework (Cobra)"},
        {"name": "Wire", "packages": ["github.com/google/wire"], "priority": 35,
         "summary": "Dependency injection (Wire)"},
    ],
    "Rust": [
        {"name": "Axum", "packages": ["axum"], "priority": 90,
         "summary": "Web framework (Axum)"},
        {"name": "Actix Web", "packages": ["actix-web"], "priority": 90,
         "summary": "Web framework (Actix)"},
        {"name": "Rocket", "packages": ["rocket"], "priority": 85,
         "summary": "Web framework (Rocket)"},
        {"name": "Warp", "packages": ["warp"], "priority": 80,
         "summary": "Web framework (Warp)"},
        {"name": "Tokio", "packages": ["tokio"], "priority": 70,
         "summary": "Async runtime (Tokio)"},
        {"name": "Serde", "packages": ["serde"], "priority": 40,
         "summary": "Serialization (Serde)"},
        {"name": "Diesel", "packages": ["diesel"], "priority": 50,
         "summary": "ORM (Diesel)"},
        {"name": "Sqlx", "packages": ["sqlx"], "priority": 45,
         "summary": "Async SQL (Sqlx)"},
        {"name": "Clap", "packages": ["clap"], "priority": 55,
         "summary": "CLI parser (Clap)"},
    ],
    "Java": [
        {"name": "Spring Boot", "packages": [
            "org.springframework.boot:spring-boot",
            "org.springframework.boot",
        ], "priority": 100,
         "summary": "Enterprise application framework (Spring Boot)"},
        {"name": "Spring", "packages": ["org.springframework:spring-core"],
         "priority": 90,
         "summary": "Application framework (Spring)"},
        {"name": "Quarkus", "packages": ["io.quarkus"], "priority": 95,
         "summary": "Cloud-native Java (Quarkus)"},
        {"name": "Micronaut", "packages": ["io.micronaut"], "priority": 95,
         "summary": "Microservice framework (Micronaut)"},
        {"name": "Vert.x", "packages": ["io.vertx"], "priority": 80,
         "summary": "Reactive toolkit (Vert.x)"},
        {"name": "Javalin", "packages": ["io.javalin"], "priority": 75,
         "summary": "Lightweight web framework (Javalin)"},
        {"name": "Hibernate", "packages": ["org.hibernate"], "priority": 50,
         "summary": "ORM (Hibernate)"},
        {"name": "JUnit", "packages": ["junit:junit", "org.junit.jupiter"],
         "priority": 30,
         "summary": "Test framework (JUnit)"},
    ],
}


# ─── Manifest Parsers ──────────────────────────────────────────


def _read_text(path: str, max_bytes: int = 256 * 1024) -> Optional[str]:
    """Read a file as UTF-8 text, return None on any I/O error."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_bytes)
    except OSError:
        return None


def _parse_package_json(workspace: str) -> Dict[str, str]:
    """Extract merged dependencies from package.json (deps + devDeps)."""
    path = os.path.join(workspace, "package.json")
    text = _read_text(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _logger.warning("[orient/framework_db] invalid package.json at %s", path)
        return {}
    deps: Dict[str, str] = {}
    deps.update(data.get("dependencies", {}) or {})
    deps.update(data.get("devDependencies", {}) or {})
    deps.update(data.get("peerDependencies", {}) or {})
    return deps


def _parse_pyproject(workspace: str) -> Dict[str, str]:
    """Extract dependencies from pyproject.toml ([project.dependencies]
    and [tool.poetry.dependencies])."""
    path = os.path.join(workspace, "pyproject.toml")
    text = _read_text(path)
    if not text:
        return {}
    deps: Dict[str, str] = {}
    # PEP 621: [project.dependencies] is a list of "name==version" strings.
    # The list may span multiple lines, so we search for ``dependencies = [``
    # and capture up to the closing ``]`` on its own line (DOTALL).
    pep621_block = re.search(
        r"^\s*\[project\]\s*$(.*?)(?=^\s*\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if pep621_block:
        block_text = pep621_block.group(1)
        m = re.search(
            r'^\s*dependencies\s*=\s*\[(.*?)\]',
            block_text, re.MULTILINE | re.DOTALL,
        )
        if m:
            # Match valid PEP 508 package names: starts with alnum/underscore,
            # followed by alnum/underscore/dot/hyphen. Stops at version
            # specifiers (>=, ==, ~=, !=), extras ([extra]), or separators.
            for item in re.findall(r'["\']([A-Za-z0-9_][A-Za-z0-9_.\-]*)', m.group(1)):
                name = item.strip().lower()
                if name:
                    deps[name] = ""
    # Poetry: [tool.poetry.dependencies] table.
    poetry_block = re.search(
        r"^\s*\[tool\.poetry\.dependencies\]\s*$(.*?)(?=^\s*\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if poetry_block:
        for line in poetry_block.group(1).splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_.\-]+)\s*=', line)
            if m and m.group(1).lower() != "python":
                deps[m.group(1).lower().replace("_", "-")] = ""
    return deps


def _parse_requirements(workspace: str) -> Dict[str, str]:
    """Extract package names from requirements.txt (best-effort)."""
    path = os.path.join(workspace, "requirements.txt")
    text = _read_text(path)
    if not text:
        return {}
    deps: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip environment markers and version specifiers.
        name = re.split(r"[=<>!~\[; ]", line, maxsplit=1)[0].strip()
        if name:
            deps[name.lower().replace("_", "-")] = ""
    return deps


def _parse_go_mod(workspace: str) -> Dict[str, str]:
    """Extract module paths from go.mod require block."""
    path = os.path.join(workspace, "go.mod")
    text = _read_text(path)
    if not text:
        return {}
    deps: Dict[str, str] = {}
    in_require = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("require"):
            # Block require: ``require (`` — must check this BEFORE the
            # single-line match, because ``require (`` also matches
            # ``^require\s+\S+`` with group = "(", which is not a dep.
            if stripped.endswith("("):
                in_require = True
                continue
            # Single-line require: ``require foo v1.0.0``
            m = re.match(r'^require\s+("[^"]+"|[A-Za-z0-9./_-]+)', stripped)
            if m:
                dep = m.group(1).strip('"')
                if dep and dep != "(":
                    deps[dep] = ""
                continue
        if in_require:
            if stripped.startswith(")"):
                in_require = False
                continue
            # ``github.com/gin-gonic/gin v1.9.0`` — take the first token
            # (the module path). Version is the second token.
            m = re.match(r'^("[^"]+"|[A-Za-z0-9._/-]+)', stripped)
            if m:
                dep = m.group(1).strip('"')
                if dep and dep != "(":
                    deps[dep] = ""
    return deps


def _parse_cargo_toml(workspace: str) -> Dict[str, str]:
    """Extract crate names from Cargo.toml [dependencies]."""
    path = os.path.join(workspace, "Cargo.toml")
    text = _read_text(path)
    if not text:
        return {}
    deps: Dict[str, str] = {}
    block = re.search(
        r"^\s*\[dependencies\]\s*$(.*?)(?=^\s*\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if block:
        for line in block.group(1).splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*=', line)
            if m:
                deps[m.group(1).lower()] = ""
    return deps


def _parse_maven_or_gradle(workspace: str) -> Dict[str, str]:
    """Extract Java dependency coordinates from pom.xml or build.gradle."""
    deps: Dict[str, str] = {}
    # pom.xml — <dependency><groupId>foo</groupId>...
    pom_path = os.path.join(workspace, "pom.xml")
    pom_text = _read_text(pom_path)
    if pom_text:
        for m in re.finditer(
            r"<groupId>\s*([^<]+?)\s*</groupId>\s*"
            r"<artifactId>\s*([^<]+?)\s*</artifactId>",
            pom_text,
        ):
            coords = f"{m.group(1)}:{m.group(2)}"
            deps[coords] = ""
            # Also index the bare artifactId so partial matches work.
            deps[m.group(2)] = ""
    # build.gradle — 'group:artifact:version' or implementation 'group:artifact'
    gradle_path = os.path.join(workspace, "build.gradle")
    gradle_text = _read_text(gradle_path)
    if not gradle_text:
        gradle_path = os.path.join(workspace, "build.gradle.kts")
        gradle_text = _read_text(gradle_path)
    if gradle_text:
        for m in re.finditer(r"([A-Za-z0-9._\-]+):([A-Za-z0-9._\-]+)", gradle_text):
            coords = f"{m.group(1)}:{m.group(2)}"
            deps[coords] = ""
            deps[m.group(2)] = ""
    return deps


# ─── Detection ─────────────────────────────────────────────────


def _collect_dependencies(workspace: str) -> Tuple[Dict[str, Dict[str, str]], str]:
    """Collect dependencies per ecosystem and pick the primary ecosystem.

    Returns ``(per_ecosystem_deps, primary_ecosystem)`` where
    ``primary_ecosystem`` is the ecosystem with the most detected
    framework hits (ties broken by the order in ECOSYSTEM_FRAMEWORKS).
    """
    parsers = {
        "Node.js": _parse_package_json,
        "Python": lambda w: {**_parse_pyproject(w), **_parse_requirements(w)},
        "Go": _parse_go_mod,
        "Rust": _parse_cargo_toml,
        "Java": _parse_maven_or_gradle,
    }
    per_ecosystem: Dict[str, Dict[str, str]] = {}
    hit_counts: Dict[str, int] = {}
    for ecosystem, parser in parsers.items():
        deps = parser(workspace)
        per_ecosystem[ecosystem] = deps
        # Count how many known framework packages appear in this ecosystem.
        hits = 0
        for fw in ECOSYSTEM_FRAMEWORKS.get(ecosystem, []):
            for pkg in fw["packages"]:
                if pkg in deps or pkg.lower() in deps:
                    hits += 1
                    break
        if hits:
            hit_counts[ecosystem] = hits
    if not hit_counts:
        # Fall back: pick whichever ecosystem had any manifest file.
        for ecosystem, deps in per_ecosystem.items():
            if deps:
                return per_ecosystem, ecosystem
        return per_ecosystem, "Unknown"
    primary_ecosystem = max(
        hit_counts, key=lambda e: (hit_counts[e], -list(ECOSYSTEM_FRAMEWORKS).index(e))
    )
    return per_ecosystem, primary_ecosystem


def _match_frameworks(
    ecosystem: str, deps: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Return framework entries whose packages appear in ``deps``."""
    matched: List[Dict[str, Any]] = []
    for fw in ECOSYSTEM_FRAMEWORKS.get(ecosystem, []):
        for pkg in fw["packages"]:
            if pkg in deps or pkg.lower() in deps:
                matched.append(fw)
                break
    matched.sort(key=lambda f: f.get("priority", 0), reverse=True)
    return matched


def _build_summary(
    ecosystem: str, primary: Optional[str], secondary: List[str]
) -> str:
    """Human-readable one-line summary of the detected stack."""
    parts: List[str] = []
    if primary:
        parts.append(primary)
    if secondary:
        parts.append(f"with {', '.join(secondary[:3])}")
    if not parts:
        return f"{ecosystem} project (no recognized frameworks)"
    return f"{ecosystem} project using " + " ".join(parts)


# @FLOW:    ORIENT_FRAMEWORK
# @CALLS:   _collect_dependencies() -> per-ecosystem deps + primary ecosystem
#           _match_frameworks() -> framework list for primary ecosystem
#           _build_summary() -> one-line stack summary
# @MUTATES: (none — pure read)


def detect_frameworks_brief(workspace: str) -> Dict[str, Any]:
    """Detect frameworks and return the orient ``framework`` block.

    Args:
        workspace: Absolute path to the project root.

    Returns:
        Dict matching the orient output schema::

            {
                "ecosystem": "Node.js",
                "primary": "Next.js" | null,
                "secondary": ["Prisma", "Jest", ...],
                "summary": "Node.js project using Next.js with Prisma, Jest"
            }
    """
    workspace = os.path.abspath(workspace)
    per_ecosystem, primary_ecosystem = _collect_dependencies(workspace)
    deps = per_ecosystem.get(primary_ecosystem, {})
    matched = _match_frameworks(primary_ecosystem, deps)

    primary = matched[0]["name"] if matched else None
    secondary = [fw["name"] for fw in matched[1:]]
    summary = _build_summary(primary_ecosystem, primary, secondary)

    return {
        "ecosystem": primary_ecosystem,
        "primary": primary,
        "secondary": secondary,
        "summary": summary,
    }

# syntax=docker/dockerfile:1.6
# CodeLens — minimal Docker image (Phase 2, issue #54)
#
# @WHO:   Dockerfile
# @WHAT:  Minimal container image for CodeLens CLI — python:3.11-slim + core deps + tree-sitter grammars
# @PART:  distribution
# @ENTRY: codelens (wrapper -> python3 /opt/codelens/scripts/codelens.py)
#
# Build:
#   docker build -t codelens:latest .
#   docker build -t codelens:maximal -f Dockerfile.maximal .
#
# Run (acceptance criterion from issue #54):
#   docker run --rm -v "$(pwd):/workspace" ghcr.io/wolfvin/codelens scan /workspace
#
# Forward-compat note: Phase 1 (PR #144) will add a `codelens` console script via
# pyproject.toml [project.scripts]. Once merged, replace the wrapper at
# /usr/local/bin/codelens with `pip install .` and drop the manual copy step.
# Until then the code uses sys.path-based imports (see pyproject.toml lines 77-79)
# and must be run via `python3 scripts/codelens.py`.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS base

# Label the image with OCI-standard metadata so GHCR / tooling can identify it.
LABEL org.opencontainers.image.title="CodeLens" \
      org.opencontainers.image.description="AI-native static code intelligence CLI + MCP server" \
      org.opencontainers.image.source="https://github.com/Wolfvin/CodeLens" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Wolfvin"

# Install runtime deps only. tree-sitter + grammar packages ship manylinux/arm64
# wheels on PyPI, so no build toolchain is required. git is needed by some
# CodeLens commands (ownership/blame, diff-base) and adds ~30MB — acceptable.
# curl is included for HEALTHCHECK debugging and download fallbacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (UID/GID 1000) for least-privilege execution.
# The user owns /workspace (the mount point) so scanned files are readable
# and generated .codelens/ artifacts are writable.
RUN groupadd --gid 1000 codelens \
    && useradd --uid 1000 --gid codelens --create-home --shell /bin/bash codelens

# Copy the repository into /opt/codelens. .dockerignore excludes tests,
# .git, benchmarks, and other build-context noise to keep layers small.
COPY --chown=codelens:codelens . /opt/codelens/

# Install Python dependencies. We install the same set that setup.sh installs
# (tree-sitter core + 6 grammars + watchdog) plus PyYAML for the rules engine.
# --no-cache-dir keeps the layer small. We do NOT `pip install .` here because
# the project has no console-script entry point yet (Phase 1 will add one).
RUN pip install --no-cache-dir \
        "tree-sitter>=0.21.0" \
        tree-sitter-html \
        tree-sitter-css \
        tree-sitter-javascript \
        tree-sitter-typescript \
        tree-sitter-rust \
        tree-sitter-python \
        watchdog \
        "PyYAML>=6.0"

# Create a wrapper script so the container exposes a `codelens` command.
# This matches the acceptance criterion `docker run ... codelens scan /workspace`
# and is forward-compatible: when Phase 1 merges, `pip install .` will overwrite
# this file with the real console-script entry point.
RUN printf '#!/bin/sh\nexec python3 /opt/codelens/scripts/codelens.py "$@"\n' \
        > /usr/local/bin/codelens \
    && chmod +x /usr/local/bin/codelens

# Default workspace mount point. Users mount their codebase here:
#   docker run -v "$(pwd):/workspace" ghcr.io/wolfvin/codelens scan /workspace
RUN mkdir -p /workspace \
    && chown codelens:codelens /workspace

USER codelens
WORKDIR /workspace

# Persist the per-user .codelens/ config dir to a volume so registry/SQLite
# state survives container restarts when the user mounts it.
ENV CODELENS_CONFIG_DIR=/home/codelens/.codelens \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1

# HEALTHCHECK: `--command-count` exercises the full command registry import
# path (loads every command module + tree-sitter grammars), so it verifies
# the runtime is functional — a deeper check than a static `--version` print.
# Interval is 30s with 30s timeout, 3 retries before unhealthy.
HEALTHCHECK --interval=30s --timeout=30s --start-period=10s --retries=3 \
    CMD codelens --command-count > /dev/null 2>&1 || exit 1

# ENTRYPOINT is the codelens wrapper so `docker run image <args>` works the
# same way `codelens <args>` works on the host. No CMD — the user must supply
# a command (scan, query, dead-code, etc.) plus the workspace path.
ENTRYPOINT ["codelens"]

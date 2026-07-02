# Docker Installation

> **Phase 2 of issue #54** — container image distribution for CodeLens.
> Images are published to GitHub Container Registry (GHCR) on every push to
> `main` and on version tags. This page covers install, usage, and the
> differences between the minimal and maximal image variants.

---

## Quick start

Pull the minimal image and scan the current directory:

```bash
docker run --rm -v "$(pwd):/workspace" ghcr.io/wolfvin/codelens scan /workspace
```

That is the acceptance criterion from issue #54: the container accepts a
CodeLens command (`scan`) plus a workspace path (`/workspace`) and runs
against the mounted host directory.

---

## Image variants

| Image | Tag | Size (approx.) | Best for |
|---|---|---|---|
| `ghcr.io/wolfvin/codelens` | `:latest`, `:v8.x.y`, `:sha-<sha>` | ~180 MB | CI pipelines, automated scans, minimal footprint |
| `ghcr.io/wolfvin/codelens:maximal-latest` | `:maximal-latest`, `:maximal-v8.x.y` | ~450 MB | Local development with `--deep` LSP-enhanced analysis |

### Minimal image (`:latest`)

Built from [`Dockerfile`](https://github.com/Wolfvin/CodeLens/blob/main/Dockerfile)
on `python:3.11-slim`. Includes:

- Python 3.11 runtime
- `tree-sitter` core + 6 grammar packages (HTML, CSS, JS, TS, Rust, Python)
- `watchdog` (file watcher) and `PyYAML` (rules engine)
- `git` (required by `ownership`, `diff-base`, and related commands)
- Runs as non-root user `codelens` (UID 1000)

The minimal image is the right default for CI: it is small, fast to pull, and
covers every CodeLens command that does not require an LSP server.

### Maximal image (`:maximal-latest`)

Built from [`Dockerfile.maximal`](https://github.com/Wolfvin/CodeLens/blob/main/Dockerfile.maximal).
In addition to everything in the minimal image, it pre-installs:

- All Python extras from `pyproject.toml` (`grammars`, `watch`, `rules`, `lsp`, `dev`)
- **LSP servers**: `python-lsp-server`, `ruff-lsp` (Python), `pyright` and
  `typescript-language-server` (JS/TS) — so `codelens <cmd> --deep` works
  out of the box without installing language servers on the host
- Node.js LTS (required by the npm-based LSP servers above)

Full LSP coverage for Rust, Go, and other languages is pending the native
LSP server issue referenced in #54. The maximal image is designed to be
extended: add more `npm install -g` / `pip install` lines as new language
servers land.

---

## Usage patterns

### One-off scan (CI style)

```bash
docker run --rm \
  -v "$(pwd):/workspace" \
  ghcr.io/wolfvin/codelens scan /workspace
```

The `--rm` flag removes the container after exit. The `$(pwd):/workspace`
bind-mount makes the host's current directory visible inside the container at
`/workspace`, which is the default `WORKDIR`.

### Persisting the `.codelens/` registry between runs

By default the per-user config dir lives at `/home/codelens/.codelens` inside
the container and is lost when the container is removed. To persist the
SQLite registry and scan cache across runs, mount a named volume:

```bash
docker volume create codelens-data

docker run --rm \
  -v "$(pwd):/workspace" \
  -v codelens-data:/home/codelens/.codelens \
  ghcr.io/wolfvin/codelens scan /workspace
```

Subsequent `query`, `dead-code`, or `trace` commands can reuse the cached
registry without re-scanning:

```bash
docker run --rm \
  -v "$(pwd):/workspace" \
  -v codelens-data:/home/codelens/.codelens \
  ghcr.io/wolfvin/codelens query 'btn-primary' /workspace
```

### Shell alias

Add to `~/.bashrc` or `~/.zshrc`:

```bash
alias codelens='docker run --rm -v "$(pwd):/workspace" -v codelens-data:/home/codelens/.codelens ghcr.io/wolfvin/codelens'
```

Then use `codelens scan .`, `codelens query 'fn' .`, etc. exactly as if it
were a locally installed binary.

### Deep analysis with LSP (maximal image only)

```bash
docker run --rm \
  -v "$(pwd):/workspace" \
  -v codelens-data:/home/codelens/.codelens \
  ghcr.io/wolfvin/codelens:maximal-latest complexity /workspace --deep
```

The `--deep` flag enables LSP-enhanced type inference and cross-file resolution.
It requires the relevant language server to be installed — which the maximal
image handles for Python and JS/TS.

### Running the MCP server

CodeLens can run as an MCP (Model Context Protocol) server over stdio. To
expose it to an MCP client running on the host:

```bash
docker run --i \
  -v "$(pwd):/workspace" \
  ghcr.io/wolfvin/codelens mcp-server /workspace
```

Note: MCP-over-stdio requires an interactive (`-i`) container. Network modes
and stdio plumbing depend on the host MCP client; consult the client's docs.

---

## Health check

Both images ship with a `HEALTHCHECK` that runs `codelens --command-count`.
This exercises the full command-registry import path (every command module +
tree-sitter grammars load), so a healthy status confirms the runtime is
functional — not just that the binary exists.

Inspect health:

```bash
docker inspect --format='{{.State.Health.Status}}' <container-id>
```

---

## Multi-arch support

Both image variants are built for `linux/amd64` and `linux/arm64` via
`docker buildx` + QEMU. Docker automatically pulls the matching architecture
for your host. To explicitly pull a different architecture:

```bash
docker pull --platform linux/arm64 ghcr.io/wolfvin/codelens:latest
```

---

## Building locally

To build the image yourself (for development or testing):

```bash
# Minimal
docker build -t codelens:local .

# Maximal
docker build -t codelens:local-maximal -f Dockerfile.maximal .

# Test
docker run --rm -v "$(pwd):/workspace" codelens:local --command-count
```

The build uses BuildKit (`# syntax=docker/dockerfile:1.6` directive at the top
of each Dockerfile), so set `DOCKER_BUILDKIT=1` if your Docker daemon is older
than 23.0.

---

## Tagging strategy

| Event | Tags produced |
|---|---|
| Push to `main` (Dockerfile changes) | `:latest`, `:sha-<short-sha>` |
| Tag push `v8.2.1` | `:v8.2.1`, `:v8.2`, `:latest` |
| Manual `workflow_dispatch` | `:latest`, `:sha-<short-sha>` (or build-only if dry-run) |

The same scheme applies to the maximal image with a `-maximal` suffix on the
image name and `maximal-` prefix on the `latest` tag (i.e. `:maximal-latest`,
`:maximal-v8.2.1`).

---

## Troubleshooting

### `permission denied` on mounted files

The container runs as UID 1000 (`codelens`). If your host files are owned by a
different UID, scans may fail to read them. Fix by either:

- `chmod -R a+r <your-project>` on the host, or
- Running with `--user $(id -u):$(id -g)` to match the host user (the
  `.codelens/` volume must then be writable by that UID).

### `codelens: command not found` inside the container

The entrypoint is the `codelens` wrapper at `/usr/local/bin/codelens`. If you
override `--entrypoint`, you must invoke `python3 /opt/codelens/scripts/codelens.py`
directly.

### LSP server not detected (minimal image)

The minimal image does not bundle LSP servers. Use the maximal image, or
install the language server on your host and drop `--deep`.

---

## Related

- Issue #54 — Distribution & packaging overhaul (this phase)
- PR #144 — Phase 1 (pip-installable package; not yet merged). Once merged,
  the Dockerfile entry point switches from the wrapper script to the
  `codelens` console script, and `pip install .` replaces the manual
  dependency install step.
- [`Dockerfile`](https://github.com/Wolfvin/CodeLens/blob/main/Dockerfile) —
  minimal image definition
- [`Dockerfile.maximal`](https://github.com/Wolfvin/CodeLens/blob/main/Dockerfile.maximal) —
  maximal image definition
- [`.github/workflows/docker-publish.yml`](https://github.com/Wolfvin/CodeLens/blob/main/.github/workflows/docker-publish.yml) —
  CI build & publish pipeline

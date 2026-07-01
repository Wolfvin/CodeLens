# Installation

CodeLens can be installed in several ways. Pick the one that fits your workflow.

## Option 1 — pip install (recommended)

```bash
pip install codelens
```

This installs the `codelens` console command and all core dependencies.
After install, run:

```bash
codelens init /path/to/your/project
codelens scan /path/to/your/project
codelens query MyFunction /path/to/your/project
```

### With optional features

```bash
# Tree-sitter grammars for AST-based analysis (recommended)
pip install "codelens[grammars]"

# YAML rule engine (Semgrep-compat rules)
pip install "codelens[rules]"

# File watcher (for `codelens watch`)
pip install "codelens[watch]"

# Native LSP server (for `codelens lsp`)
pip install "codelens[lsp]"

# Everything (for development)
pip install "codelens[all]"
```

## Option 2 — pipx (isolated environment)

```bash
pipx install codelens
```

[pipx](https://pypa.github.io/pipx/) installs CodeLens in an isolated
environment so it doesn't conflict with your system Python packages.
The `codelens` command is available on your PATH.

## Option 3 — python -m codelens

If you prefer not to install a console script:

```bash
pip install codelens
python -m codelens scan /path/to/your/project
```

## Option 4 — from source (legacy mode)

```bash
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens
pip install -e .
```

After install, both `codelens` (console command) and
`python3 scripts/codelens.py` (legacy mode) work. The legacy mode
prints a one-time deprecation warning pointing you to the console
command.

### Running without install

You can also run CodeLens directly from a source checkout without
installing:

```bash
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens
PYTHONUTF8=1 python3 scripts/codelens.py scan .
```

This is the original invocation method and remains fully supported.

## Requirements

- Python 3.8+
- `tree-sitter>=0.21.0` (installed automatically by pip)

### Optional dependencies

| Extra | What it provides | Install |
|-------|------------------|---------|
| `grammars` | tree-sitter grammars for Python, JS, TS, Rust, HTML, CSS | `pip install "codelens[grammars]"` |
| `rules` | PyYAML for YAML rule engine | `pip install "codelens[rules]"` |
| `watch` | watchdog for `codelens watch` file monitoring | `pip install "codelens[watch]"` |
| `lsp` | pygls + lsprotocol for native LSP server | `pip install "codelens[lsp]"` |
| `dev` | pytest + pytest-cov for development | `pip install "codelens[dev]"` |
| `all` | All of the above | `pip install "codelens[all]"` |

## Verifying the install

```bash
codelens --command-count    # Should print a number (67+)
codelens init /tmp/test     # Initialize a test workspace
codelens scan /tmp/test     # Scan it
```

## Troubleshooting

### `codelens: command not found` after pip install

Your pip bin directory may not be on PATH. Either:

- Add it to PATH: `export PATH="$HOME/.local/bin:$PATH"`
- Or use `python -m codelens` instead
- Or use `pipx install codelens` which handles PATH automatically

### UnicodeEncodeError on Windows

Set `PYTHONUTF8=1` before running codelens:

```cmd
set PYTHONUTF8=1
codelens scan C:\path\to\project
```

### Tree-sitter grammar not found

Install the grammars extra:

```bash
pip install "codelens[grammars]"
```

Without grammars, CodeLens falls back to regex-based parsing which has
lower accuracy but works everywhere.

## Upcoming distribution channels (issue #54)

Phase 1 (this release) covers pip / pipx / source. Future phases will add:

- **Phase 2**: Docker image (`docker run ghcr.io/wolfvin/codelens`)
- **Phase 3**: Self-contained binary (no Python needed)
- **Phase 4**: Homebrew (`brew install wolfvin/tap/codelens`), Scoop, Nix
- **Phase 5**: Release signing (minisign + Cosign)
- **Phase 6**: Auto-update command (`codelens upgrade`)

See [issue #54](https://github.com/Wolfvin/CodeLens/issues/54) for the
full roadmap.

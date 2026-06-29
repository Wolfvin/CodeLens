# Contributing to CodeLens

First off, thank you for considering contributing to CodeLens! It's people like you that make CodeLens such a great tool.

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues as you might find that the issue has already been reported. When you create a bug report, include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples** (sample code, workspace structure)
- **Describe the behavior you observed** and the behavior you expected
- **Include the full command and output**
- **Include your environment**: OS, Python version, tree-sitter version

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a step-by-step description** of the suggested enhancement
- **Provide specific examples** demonstrating how it would be used
- **Describe the current behavior** and explain the expected behavior
- **Explain why this enhancement would be useful** to most CodeLens users

### Adding New Parsers or Engines

CodeLens uses a modular engine architecture. To add a new analysis capability:

1. **Check existing issues** for similar proposals
2. **Decide: plugin or built-in?** — Since v8.0, CodeLens supports plugins (rule_pack / engine / formatter / command). If your analysis is self-contained, ship it as a plugin (see `scripts/plugin_system.py`). If it needs tight integration with the registry or other engines, add it as built-in.
3. **For built-in engines**: Follow the naming convention `yourfeature_engine.py`
4. **Implement the engine** following the pattern of existing engines (return `{status, workspace, findings, summary}`)
5. **Add a command module** in `commands/yourfeature.py` with `add_args(subparser)` and `execute(args)` functions
6. **Add tests** in `tests/`
7. **Sync command counts** — see "Syncing Command Counts" below; do NOT hand-edit the count in `README.md`, `SKILL.md`, `SKILL-QUICK.md`, `pyproject.toml`, `skill.json`, or `scripts/mcp_server.py`
8. **Update documentation** in `SKILL.md`, `SKILL-QUICK.md`, `README.md`, and `CHANGELOG.md`

Commands auto-register via `commands/__init__.py` — no manual wiring needed.

### Syncing Command Counts (issue #38)

The number of CLI commands and MCP tools must never be hand-edited in
documentation or metadata files — it drifts every time a command is added or
removed. The single source of truth is the runtime `COMMAND_REGISTRY` (and
`_TOOL_DEFINITIONS` for MCP static tools). The `scripts/sync_command_count.py`
helper propagates the runtime count into every doc/metadata file.

When you add or remove a command:

```bash
# 1. Run the sync helper in --check mode to see what would change:
PYTHONPATH=scripts python3 scripts/sync_command_count.py --check

# 2. Apply the changes:
PYTHONPATH=scripts python3 scripts/sync_command_count.py --apply

# 3. Update the strict regression sentinel in tests/test_integration.py
#    (TestModuleStructure.test_command_registry_has_all_commands)
#    to match the new len(COMMAND_REGISTRY). This is the ONE place where
#    the count is intentionally hardcoded — it is the regression anchor.

# 4. Verify:
PYTHONPATH=scripts python3 -m pytest tests/test_command_count.py tests/test_integration.py::TestModuleStructure -v
```

The test suite enforces this in CI:

- `tests/test_command_count.py::test_all_docs_in_sync_with_command_registry`
  fails if any doc/metadata file mentions a stale count.
- `tests/test_integration.py::TestModuleStructure::test_command_registry_has_all_commands`
  fails if `len(COMMAND_REGISTRY)` changes in either direction (strict `==`,
  not `>=`).

### Adding New Language Parsers

1. **Check tree-sitter support** for the language
2. **Create `parsers/yourlanguage_parser.py`** following the `base_parser.py` pattern (preferred for accuracy)
3. **Always add a fallback regex parser** in `parsers/fallback_yourlanguage.py` so the language works even without tree-sitter installed
4. **Update file discovery** in `commands/scan.py` to recognize the file extension
5. **Update `setup.sh`** to install the tree-sitter grammar (if applicable)
6. **Update `framework_detect.py`** if the language has framework markers worth detecting
7. **Add tests** with sample files in the target language
8. **Update `references/parser-rules.md`** with the new language's parsing rules
9. **Update `README.md`** supported languages list

## Development Setup

```bash
# Clone the repository
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens

# Run setup
bash setup.sh

# Create a branch for your changes
git checkout -b feature/your-feature-name

# Run tests
python3 -m pytest tests/ -v

# Or run specific test file
python3 -m pytest tests/test_html_parser.py -v
```

## Coding Standards

### Python Style

- Follow **PEP 8** style guidelines
- Use **type hints** for all function signatures
- Use **docstrings** (triple-quoted) for all public functions and classes
- Keep functions focused — one function does one thing
- Maximum line length: **120 characters**

### Engine Architecture

Each engine follows this pattern:

```python
"""
Engine Name for CodeLens — vX
Brief description of what the engine does.
Answers: "What question does this answer?"
"""

from typing import Dict, List, Any


def your_engine(workspace: str, **kwargs) -> Dict[str, Any]:
    """
    Run the engine analysis.
    
    Args:
        workspace: Absolute path to workspace root
        **kwargs: Engine-specific options
    
    Returns:
        Dict with structured results following the standard format:
        {
            "status": "ok",
            "workspace": str,
            "findings": [...],
            "summary": {...}
        }
    """
    pass
```

### CLI Integration

When adding a new CLI command, create a new file in the `commands/` directory:

1. Create `commands/yourfeature.py` with two functions:
   - `add_args(subparser)` — define argparse arguments
   - `execute(args)` — run the command and return JSON
2. The command auto-registers via `commands/__init__.py` (no manual wiring)
3. Update `skill.json` version and description
4. Add a formatter in `formatters/` if markdown output is needed

### Error Handling

- Use **graceful degradation** — if tree-sitter fails, fall back to regex
- Never crash the CLI — always return structured JSON with error info
- Log warnings to stderr, not stdout
- Handle missing files, encoding errors, and permission issues

### Testing

- Write tests for **all new engines and parsers**
- Use **sample code fixtures** in tests (not real codebases)
- Test **edge cases**: empty files, files with only comments, binary files
- Test **error recovery**: missing registry, corrupt JSON, missing tree-sitter
- Run the full test suite before submitting: `python3 -m pytest tests/ -v`

## Pull Request Process

1. **Update documentation** — README.md, SKILL.md, SKILL-QUICK.md, changelog.md
2. **Add tests** for new features
3. **Ensure all tests pass** — `python3 -m pytest tests/ -v`
4. **Follow the PR template** — describe changes, motivation, testing
5. **One PR per feature** — keep PRs focused and reviewable
6. **Update skill.json version** if adding new commands

### PR Title Format

- `feat: add Python parser` — New feature
- `fix: handle empty CSS files` — Bug fix
- `docs: update README` — Documentation
- `refactor: simplify edge resolver` — Refactoring
- `test: add Rust parser tests` — Tests
- `chore: update dependencies` — Maintenance

## Release Process

Maintainers follow this process:

1. Update version in `scripts/utils.py` (`CODELENS_VERSION` constant), `skill.json`, and `pyproject.toml`
2. Update `CHANGELOG.md` (top-level) and `references/changelog.md` (per-version highlights)
3. Update `SKILL.md`, `SKILL-QUICK.md`, and `README.md` version numbers
4. Tag release: `git tag v8.x.x`
5. Push tag: `git push origin v8.x.x`

## Questions?

Feel free to open a GitHub issue with the `question` label, or start a discussion in the Discussions tab.

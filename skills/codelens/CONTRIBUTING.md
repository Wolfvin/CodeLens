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
2. **Open a discussion issue** first describing the engine's purpose and design
3. **Follow the naming convention**: `yourfeature_engine.py`
4. **Implement the engine** following the pattern of existing engines
5. **Add CLI integration** in `codelens.py`
6. **Add tests** in `tests/`
7. **Update documentation** in `SKILL.md`, `SKILL-QUICK.md`, and `README.md`

### Adding New Language Parsers

1. **Check tree-sitter support** for the language
2. **Create `parsers/yourlanguage_parser.py`** following the base_parser pattern
3. **Add fallback regex parser** in `codelens.py` for when tree-sitter is unavailable
4. **Update `discover_files()`** in `codelens.py` to recognize the file extension
5. **Update `setup.sh`** to install the tree-sitter grammar
6. **Add tests** with sample files in the target language
7. **Update documentation**

## Development Setup

```bash
# Clone the repository
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens/skills/codelens

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

When adding a new CLI command, follow this pattern in `codelens.py`:

1. Add a `cmd_yourfeature()` function
2. Add argparse subparser in `main()`
3. Add the command dispatch in the if/elif chain
4. Update the module docstring usage section
5. Update `skill.json` version and description

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

1. Update version in `skill.json`
2. Update `references/changelog.md`
3. Tag release: `git tag v5.x.x`
4. Push tag: `git push origin v5.x.x`

## Questions?

Feel free to open a GitHub issue with the `question` label, or start a discussion in the Discussions tab.

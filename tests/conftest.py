"""Shared pytest configuration for CodeLens."""

import os

# Fail fast when command modules fail to import during test runs.
os.environ.setdefault("CODELENS_STRICT_COMMANDS", "1")

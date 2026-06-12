# CodeLens Parsers
# Each parser extracts references from source files and returns structured data.

from parsers.fallback_kotlin import parse_kotlin_fallback

__all__ = ["parse_kotlin_fallback"]

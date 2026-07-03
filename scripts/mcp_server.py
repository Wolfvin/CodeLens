#!/usr/bin/env python3
"""
CodeLens MCP Server — Model Context Protocol server for AI agent integration.

Implements the MCP specification (2025-03-26) over stdio (JSON-RPC 2.0).
Provides persistent server mode with in-memory registry caching, sub-millisecond
query latency after initial scan, and automatic tool discovery for all 63 CodeLens commands.

Usage:
    python3 codelens.py serve                        # Start MCP server (stdio transport)
    python3 codelens.py serve --watch                # Auto-watch mode for live updates
    python3 codelens.py serve --port 8080            # HTTP/SSE transport (optional)

MCP Protocol:
    - JSON-RPC 2.0 over stdio (stdin/stdout)
    - Initialize handshake with server capabilities
    - tools/list: returns all CodeLens commands as MCP tools
    - tools/call: executes a CodeLens command and returns result
    - resources/list: expose codebase registry as resources
    - All responses use --format ai (normalized schema)

Benefits over CLI mode:
    - Single process, no cold start (vs 200-500ms per CLI invocation)
    - Registry loaded once, kept in memory
    - Sub-millisecond query latency after initial scan
    - Background file watching for auto-updates
    - Smart caching with invalidation on file changes
"""

import sys
import os
import json
import signal
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime, timezone

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import logger, CODELENS_VERSION

# ─── MCP Protocol Constants ──────────────────────────────────────────

MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_SERVER_NAME = "codelens"
MCP_SERVER_VERSION = CODELENS_VERSION

# ─── Tool Schema Definitions ──────────────────────────────────────────
# Maps each CodeLens command to an MCP tool with proper JSON Schema params.

_TOOL_DEFINITIONS = {
    "scan": {
        "description": "Scan workspace and build codebase registry. This is the first command to run before any analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "incremental": {
                    "type": "boolean",
                    "description": "Only scan changed files (faster, requires previous scan)",
                    "default": False
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum number of files to scan (default: 5000)",
                    "default": 5000
                }
            },
            "required": ["workspace"]
        }
    },
    "query": {
        "description": "Look up a symbol (function/class/variable/CSS class/ID) in the codebase registry. Returns action recommendation (CREATE/EXTEND/ASK/STOP).",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to query (symbol, CSS class, ID, or file path)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "domain": {
                    "type": "string",
                    "enum": ["frontend", "backend"],
                    "description": "Domain to search (frontend or backend)"
                },
                "file": {
                    "type": "string",
                    "description": "Filter by file path substring"
                },
                "fuzzy": {
                    "type": "boolean",
                    "description": "Enable fuzzy/substring matching (case-insensitive)",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Max callers/callees to return (default: 20)",
                    "default": 20
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "list": {
        "description": "List registry entries with optional filter and pagination.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "domain": {
                    "type": "string",
                    "enum": ["frontend", "backend", "all"],
                    "description": "Domain to list",
                    "default": "all"
                },
                "filter": {
                    "type": "string",
                    "enum": ["all", "dead", "duplicate_define", "duplicate_ref", "collision", "active"],
                    "description": "Filter by status",
                    "default": "all"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 200)",
                    "default": 200
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset for pagination (default: 0)",
                    "default": 0
                }
            },
            "required": ["workspace"]
        }
    },
    "symbols": {
        "description": "Search symbols in registry by name with optional fuzzy matching.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name to search"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "domain": {
                    "type": "string",
                    "enum": ["frontend", "backend", "all"],
                    "description": "Domain to search",
                    "default": "all"
                },
                "fuzzy": {
                    "type": "boolean",
                    "description": "Allow partial/fuzzy matching",
                    "default": False
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "search": {
        "description": "Search code pattern across workspace using regex or text matching.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (text or regex)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["pattern", "workspace"]
        }
    },
    "trace": {
        "description": "Trace deep call chain from a symbol. Shows the full execution path.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Function/symbol name to trace"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "direction": {
                    "type": "string",
                    "enum": ["callers", "callees", "both"],
                    "description": "Trace direction",
                    "default": "both"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum trace depth (default: 5)",
                    "default": 5
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "impact": {
        "description": "Analyze change impact for a symbol. Shows what would be affected by changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name to analyze impact for"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "context": {
        "description": "Get rich context about a symbol: definition, callers, callees, type info, and related code.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name to get context for"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "dependents": {
        "description": "Module-level import tracking. Find all files that depend on a given module.",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "File path to trace dependents for"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["file", "workspace"]
        }
    },
    "outline": {
        "description": "Get file structure outline. Shows functions, classes, and their locations.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "file": {
                    "type": "string",
                    "description": "Specific file to outline (optional, outlines entire workspace if omitted)"
                }
            },
            "required": ["workspace"]
        }
    },
    "complexity": {
        "description": "Compute cyclomatic/cognitive complexity for functions in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "name": {
                    "type": "string",
                    "description": "Specific function to analyze"
                },
                "file": {
                    "type": "string",
                    "description": "Filter by file path"
                },
                "threshold": {
                    "type": "integer",
                    "description": "Minimum complexity threshold to report"
                },
                "sort": {
                    "type": "string",
                    "enum": ["complexity", "cognitive", "loc"],
                    "description": "Sort results by metric"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of functions to return"
                }
            },
            "required": ["workspace"]
        }
    },
    "smell": {
        "description": "Detect code smells across workspace. Returns health score and prioritized findings.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories to check: long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent"
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "Filter by severity level"
                }
            },
            "required": ["workspace"]
        }
    },
    "dead-code": {
        "description": "Enhanced dead code detection. Finds unused functions, variables, and imports.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "circular": {
        "description": "Detect circular dependencies in the codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "missing-refs": {
        "description": "Detect CSS/HTML reference mismatches. Find unused CSS and missing styles.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "dataflow": {
        "description": "Trace data flow from source to sink. Track how user input, env vars, and other data moves through the codebase, including cross-file flow via imports. Detects unsanitized taint paths that lead to security vulnerabilities.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "source": {
                    "type": "string",
                    "description": "Filter by source type (e.g., 'user_input', 'env_var', or a variable name)"
                },
                "sink": {
                    "type": "string",
                    "description": "Filter by sink type (e.g., 'db_query', 'html_output')"
                }
            },
            "required": ["workspace"]
        }
    },
    "side-effect": {
        "description": "Analyze function side effects. Find functions with global state mutations, I/O, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "name": {
                    "type": "string",
                    "description": "Specific function to analyze"
                }
            },
            "required": ["workspace"]
        }
    },
    "refactor-safe": {
        "description": "Pre-flight rename/move safety check. Assesses risk of refactoring a symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name to check refactoring safety for"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "stack-trace": {
        "description": "Simulate error propagation / stack trace from a function.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Function name to simulate error propagation from"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["name", "workspace"]
        }
    },
    "secrets": {
        "description": "Detect hardcoded secrets, API keys, and credentials in source code.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "semantic-query": {
        "description": (
            "Semantic symbol search via TF-IDF (issue #11). Finds symbols by "
            "meaning, not just by name — e.g. querying 'user authentication flow' "
            "can surface a function named verify_jwt_claims. Returns ranked symbols "
            "with cosine-similarity scores. Pure-Python, zero dependencies; reads "
            "from the existing SQLite registry so the index is always in sync with "
            "the last 'scan' result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language or code-fragment query, e.g. "
                        "'user authentication flow', 'parse jwt', 'error handler'. "
                        "Symbol names, signatures, kinds, and file paths are all "
                        "included in the TF-IDF document for each symbol."
                    )
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "top": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10; use 0 for all).",
                    "default": 10
                }
            },
            "required": ["query", "workspace"]
        }
    },
    "vuln-scan": {
        "description": "Scan dependencies for known CVEs and security vulnerabilities.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "perf-hint": {
        "description": "Detect performance anti-patterns (N+1 queries, unnecessary re-renders, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "a11y": {
        "description": "Detect accessibility issues in HTML/frontend code.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "css-deep": {
        "description": "Deep CSS analysis: variables, keyframes, specificity conflicts, unused selectors.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "regex-audit": {
        "description": "Audit regex patterns for ReDoS vulnerabilities and correctness issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "entrypoints": {
        "description": "Map execution entry points (main, handlers, routes, exports).",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "api-map": {
        "description": "Map REST/GraphQL routes to their handler functions.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "state-map": {
        "description": "Track global state management (Redux stores, context providers, global variables).",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "env-check": {
        "description": "Audit environment variables: missing, unused, and hardcoded values.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "debug-leak": {
        "description": "Detect leftover debug code: console.log, print statements, debug flags.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "ownership": {
        "description": "Git blame-based code ownership analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "test-map": {
        "description": "Test coverage mapping: which functions are tested and which are not.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "config-drift": {
        "description": "Dependency drift detection: outdated and conflicting dependency versions.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "type-infer": {
        "description": "Lightweight type inference for dynamically-typed code.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "diff": {
        "description": "Compare registry snapshots to detect codebase changes over time.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "detect": {
        "description": "Detect frameworks and technologies used in the project.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "init": {
        "description": "Initialize CodeLens configuration for a workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "summary": {
        "description": "Auto-summary with prioritized, condensed output. The primary anti-overload command for AI agents.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "architecture": {
        "description": "Single-call codebase overview for AI agent orientation (issue #19). Returns languages, frameworks, entry points, packages, top routes, graph hotspots, and total symbol count in one call. Use --lite for <1k token orientation mode that omits routes/packages/hotspots. Result is cached in .codelens/architecture_cache.json and invalidated on re-scan.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "lite": {
                    "type": "boolean",
                    "description": "Lite mode: return only languages, frameworks, entry_points, total_symbols (omits routes/packages/hotspots). Targets <1k tokens output for cheap agent orientation.",
                    "default": False
                }
            },
            "required": ["workspace"]
        }
    },
    "analyze": {
        "description": "Full repository analysis in a single command. The ultimate one-shot command for understanding an entire repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "focus": {
                    "type": "string",
                    "enum": ["security", "quality", "architecture", "all"],
                    "description": "Focus area for analysis (default: all)",
                    "default": "all"
                },
                "detail": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full"],
                    "description": "Detail level (default: standard)",
                    "default": "standard"
                },
                "skip_scan": {
                    "type": "boolean",
                    "description": "Skip init+scan if registry already exists",
                    "default": False
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum items per category (default: 15)",
                    "default": 15
                },
                "timeout": {
                    "type": "integer",
                    "description": "Total time budget in seconds for analysis engines (default: 300)",
                    "default": 300
                }
            },
            "required": ["workspace"]
        }
    },
    "handbook": {
        "description": "Generate project handbook for AI agents. Comprehensive documentation of the codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "ask": {
        "description": "Ask a natural language question about the codebase. AI-powered codebase Q&A.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about the codebase"
                },
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["question"]
        }
    },
    "artifact-scan": {
        "description": "Scan for build artifacts and generated files that should be gitignored.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "binary-scan": {
        "description": "Scan for binary files that may be accidentally committed.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": ["workspace"]
        }
    },
    "fix": {
        "description": "Auto-fix issues with confidence scoring. Supports secrets masking, dead-code removal, debug-leak cleanup, and import cleanup. Uses dry-run by default — use --apply to actually modify files.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["secrets_mask", "dead_code", "debug_leak", "import_cleanup", "todo_fixme"]},
                    "description": "Fix categories to apply (default: all)"
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Show what would be changed without modifying files (default: true)",
                    "default": True
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold 0-1 (default: 0.5)",
                    "default": 0.5
                },
                "max_risk": {
                    "type": "string",
                    "enum": ["safe", "moderate", "risky", "dangerous"],
                    "description": "Maximum risk level to apply (default: risky)",
                    "default": "risky"
                }
            },
            "required": ["workspace"]
        }
    },
    "check": {
        "description": "CI/CD quality gate. Runs multiple analysis commands and exits non-zero if quality threshold is not met. Supports SARIF output for GitHub Advanced Security integration.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Minimum severity to fail the gate (default: high)",
                    "default": "high"
                },
                "max_findings": {
                    "type": "integer",
                    "description": "Maximum allowed findings (0 = no limit, default: 0)",
                    "default": 0
                },
                "health_min": {
                    "type": "integer",
                    "description": "Minimum health score to pass 0-100 (default: 0)",
                    "default": 0
                },
                "sarif": {
                    "type": "boolean",
                    "description": "Also output SARIF format for GitHub Advanced Security",
                    "default": False
                },
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Commands to run for the quality gate",
                    "default": ["secrets", "dead-code", "smell", "complexity", "debug-leak", "circular", "taint"]
                }
            },
            "required": ["workspace"]
        }
    },
    "guard": {
        "description": "Pre/post-write verification for AI agents. Use 'pre' before making changes to check safety, 'post' after to verify no new issues were introduced. The killer feature for AI-native code intelligence.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "action": {
                    "type": "string",
                    "enum": ["pre", "post", "snapshot", "verify"],
                    "description": "Guard action: pre (before write), post (after write), snapshot (save state), verify (compare with snapshot)"
                },
                "file": {
                    "type": "string",
                    "description": "File path being modified (for pre/post actions)"
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol being added/modified/removed (for pre action)"
                },
                "change_type": {
                    "type": "string",
                    "enum": ["create", "modify", "delete", "rename"],
                    "description": "Type of change (default: modify)",
                    "default": "modify"
                }
            },
            "required": ["workspace", "action"]
        }
    },
    "taint": {
        "description": "AST-based taint analysis for vulnerability detection. Tracks data flow from sources (user input, env vars) through assignments and function calls to sinks (SQL queries, command execution, HTML output), checking for sanitizers in the taint path. More precise than regex-based dataflow analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "typescript"],
                    "description": "Language to analyze (auto-detected if omitted)"
                }
            },
            "required": ["workspace"]
        }
    },
    "plugin": {
        "description": "Manage CodeLens plugins. List installed plugins, install new ones from a directory or URL, and run plugin-provided analysis commands. Plugins extend CodeLens with custom rules and engines.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "install", "run", "uninstall"],
                    "description": "Plugin action (default: list)",
                    "default": "list"
                },
                "name": {
                    "type": "string",
                    "description": "Plugin name (for install/run/uninstall)"
                },
                "source": {
                    "type": "string",
                    "description": "Plugin source path or URL (for install)"
                }
            },
            "required": ["workspace"]
        }
    },
    "graph-schema": {
        "description": "Return the shape of the code graph: node + edge counts, node type distribution (function/class/...), edge type distribution (CALLS/IMPORTS/...), and index count. The cheapest way to understand the graph before issuing structural queries. Returns zeros when scan has not been run.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "db_path": {
                    "type": "string",
                    "description": "Custom SQLite db path (default: <workspace>/.codelens/codelens.db)"
                }
            },
            "required": ["workspace"]
        }
    },
    # ── Issue #121: MCP tools for commands added in #107, #109, #110 ──
    "arch-metrics": {
        "description": (
            "Compute architecture metrics: fan-in, fan-out, instability "
            "(fan_out / (fan_in + fan_out)), and god-module flags. Requires "
            "a prior 'scan' to populate the graph. Useful for spotting "
            "highly-depended-on modules (low instability) vs. leaf modules "
            "(high instability) and detecting god modules with excessive fan-in."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown", "ai", "sarif", "compact"],
                    "description": "Output format (default: ai — normalized schema)",
                    "default": "ai"
                },
                "top": {
                    "type": "integer",
                    "description": "Limit results to top N modules by instability (default: 50)",
                    "default": 50
                }
            },
            "required": ["workspace"]
        }
    },
    "memory": {
        "description": (
            "Serena-style markdown memory system for cross-session AI context. "
            "Actions: write <name> <content>, read <name>, list, delete <name>. "
            "Memories are stored as .codelens/memories/<name>.md (project scope) "
            "or ~/.codelens/memories/global/<name>.md (global scope). 'mem:NAME' "
            "references in content are validated — broken refs emit warnings but "
            "the write always succeeds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "action": {
                    "type": "string",
                    "enum": ["write", "read", "list", "delete"],
                    "description": "Memory action to perform"
                },
                "name": {
                    "type": "string",
                    "description": "Memory name (required for write/read/delete). Must start with a letter; letters/digits/_/-/. only."
                },
                "content": {
                    "type": "string",
                    "description": "Memory content in markdown (required for write). May include 'mem:NAME' references."
                }
            },
            "required": ["workspace", "action"]
        }
    },
    "export-snapshot": {
        "description": (
            "Export the CodeLens graph (nodes + edges + metadata) as a "
            "compressed .codelens.gz snapshot for sharing across team members "
            "or CI environments. Snapshot contains graph metadata only — no "
            "file content. Companion to import-snapshot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "output": {
                    "type": "string",
                    "description": "Output path (default: <workspace>/.codelens/snapshot.codelens.gz)"
                }
            },
            "required": ["workspace"]
        }
    },
    "import-snapshot": {
        "description": (
            "Import a CodeLens snapshot (.codelens.gz) into the workspace DB. "
            "Useful for CI: run scan on a build machine, export snapshot, "
            "import on developer machines to skip the parse cost. Mode "
            "'replace' (default) wipes existing graph; 'merge' adds to it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "input": {
                    "type": "string",
                    "description": "Input snapshot path (default: <workspace>/.codelens/snapshot.codelens.gz)"
                },
                "merge": {
                    "type": "boolean",
                    "description": "Merge with existing graph instead of replacing (default: False)",
                    "default": False
                }
            },
            "required": ["workspace"]
        }
    },
    "manage-adr": {
        "description": (
            "Architecture Decision Records (ADR) manager — persistent memory "
            "of *why* the codebase is structured the way it is, so agents "
            "don't propose refactors that violate intentional constraints. "
            "Backed by SQLite at .codelens/adrs.db. Actions: "
            "create <title> [context] [decision] [status], "
            "list [status_filter], get <id>, "
            "update <id> [title] [context] [decision] [status], "
            "deprecate <id> [superseded_by], delete <id>. "
            "Statuses: proposed (default), accepted, deprecated, rejected. "
            "Prefer 'deprecate' over 'delete' to preserve history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                },
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "update", "deprecate", "delete"],
                    "description": "ADR action to perform"
                },
                "id": {
                    "type": "integer",
                    "description": "ADR id (required for get/update/deprecate/delete). Positive integer."
                },
                "title": {
                    "type": "string",
                    "description": "Short title (required for create, optional for update). E.g. 'Use SQLite over PostgreSQL'."
                },
                "context": {
                    "type": "string",
                    "description": "Background and constraints driving the decision (optional for create/update)."
                },
                "decision": {
                    "type": "string",
                    "description": "The decision itself — what was chosen and why (optional for create/update)."
                },
                "status": {
                    "type": "string",
                    "enum": ["proposed", "accepted", "deprecated", "rejected"],
                    "description": "ADR status. Default for create is 'proposed'."
                },
                "superseded_by": {
                    "type": "integer",
                    "description": "Id of the replacement ADR (optional, for deprecate action). Must exist and differ from id."
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["proposed", "accepted", "deprecated", "rejected"],
                    "description": "Filter list action by status (optional)."
                }
            },
            "required": ["workspace", "action"]
        }
    },
}


# ─── Tool Schema Helpers ──────────────────────────────────────────────


# Format enum shared by every tool's inputSchema (issue #17).
# compact = token-efficient single-char keys + abbreviated types.
_FORMAT_PROPERTY = {
    "type": "string",
    "enum": ["json", "markdown", "ai", "sarif", "compact"],
    "description": (
        "Output format. 'ai' (default) is the normalized schema; 'compact' "
        "uses single-character keys and abbreviated types to cut tokens "
        "40-70%. 'json'/'markdown'/'sarif' are the legacy verbose forms."
    ),
    "default": "ai",
}


def _inject_format_enum(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``schema`` with the shared ``format`` property added.

    Avoids mutating the static ``_TOOL_DEFINITIONS`` dict in place so the
    original schemas remain available for inspection. Idempotent: if the
    schema already declares a ``format`` property it is left untouched.
    """
    if not isinstance(schema, dict):
        return schema
    out = json.loads(json.dumps(schema))  # deep copy via JSON (schemas are JSON-serializable)
    props = out.setdefault("properties", {})
    if isinstance(props, dict) and "format" not in props:
        props["format"] = dict(_FORMAT_PROPERTY)
    return out


# ─── Smart Caching Layer ──────────────────────────────────────────────

class MCPCache:
    """In-memory cache for MCP server with TTL and invalidation support.

    Caches:
    - Registry data (frontend.json / backend.json) per workspace
    - Analysis results per (command, workspace) key
    - Auto-invalidates on file change events
    """

    def __init__(self, default_ttl: float = 300.0):
        self._cache: Dict[str, Tuple[Any, float, float]] = {}  # key -> (value, created_at, ttl)
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value. Returns None if not found or expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, created_at, ttl = entry
            if ttl > 0 and (time.time() - created_at) > ttl:
                del self._cache[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a cached value with optional TTL (0 = never expire)."""
        with self._lock:
            self._cache[key] = (value, time.time(), ttl if ttl is not None else self._default_ttl)

    def invalidate(self, prefix: str = "") -> int:
        """Invalidate cache entries matching a prefix. Returns count of invalidated entries."""
        with self._lock:
            if not prefix:
                count = len(self._cache)
                self._cache.clear()
                return count
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
            return len(keys_to_delete)

    def invalidate_workspace(self, workspace: str) -> int:
        """Invalidate all cache entries for a specific workspace."""
        ws_key = workspace.rstrip("/")
        return self.invalidate(f"registry:{ws_key}:") + self.invalidate(f"cmd:{ws_key}:")

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            }


# ─── MCP Server Core ──────────────────────────────────────────────────

class MCPServer:
    """CodeLens MCP Server implementing JSON-RPC 2.0 over stdio.

    Features:
    - Initialize handshake with capabilities
    - tools/list: returns all CodeLens commands as MCP tools
    - tools/call: executes a CodeLens command and returns result
    - resources/list: expose codebase registry as resources
    - Persistent registry caching in memory
    - Sub-millisecond query latency after initial scan
    - Graceful shutdown on stdin close or SIGTERM
    """

    def __init__(self, watch: bool = False):
        self._initialized = False
        self._cache = MCPCache(default_ttl=300.0)
        self._watch = watch
        self._watcher = None
        self._watcher_thread = None
        self._shutting_down = False
        self._request_count = 0
        self._start_time = time.time()
        self._client_info = {}
        self._command_registry = None  # Lazy loaded
        self._workspace_registries: Dict[str, Dict[str, Any]] = {}  # In-memory registry cache
        # Hook manager (issue #47 Phase 1) — defaults to all hooks disabled.
        # Bound to a workspace lazily on first tool call so the manager
        # picks up the auto-detected workspace.
        self._hook_manager: Optional[HookManager] = None
        self._hook_workspace: Optional[str] = None
        # Worktree mismatch cache (issue #66 Phase 4). Detection
        # shells out to git twice — too expensive to repeat on every
        # MCP tool call. Cache the result per workspace for the
        # server's lifetime. ``None`` means "not yet probed";
        # ``{}`` (empty dict) means "probed, no mismatch"; a
        # populated dict means "probed, mismatch present".
        self._worktree_mismatch_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    # ─── Lifecycle ────────────────────────────────────────

    def start(self) -> None:
        """Start the MCP server. Reads JSON-RPC from stdin, writes to stdout."""
        import select

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Log to stderr (stdout is for JSON-RPC)
        print(f"[CodeLens MCP] Server starting (PID {os.getpid()})", file=sys.stderr)

        # Read JSON-RPC messages from stdin
        reader = sys.stdin
        writer = sys.stdout

        while not self._shutting_down:
            try:
                # Use select to make stdin reading interruptible
                # This allows signal handlers to run between reads
                if hasattr(select, 'select'):
                    # Unix: use select() with a 1-second timeout
                    ready, _, _ = select.select([reader], [], [], 1.0)
                    if not ready:
                        # Timeout — check _shutting_down and loop
                        continue
                    line = reader.readline()
                else:
                    # Windows fallback: just readline with a poll
                    line = reader.readline()

                if not line:
                    # stdin closed — graceful shutdown
                    print("[CodeLens MCP] stdin closed, shutting down", file=sys.stderr)
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse and handle the JSON-RPC message
                response = self._handle_message(line)
                if response is not None:
                    response_str = json.dumps(response, ensure_ascii=False)
                    writer.write(response_str + "\n")
                    writer.flush()

            except KeyboardInterrupt:
                print("[CodeLens MCP] KeyboardInterrupt, shutting down", file=sys.stderr)
                break
            except Exception as e:
                # Never crash the server on a bad message
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": str(e)
                    }
                }
                try:
                    writer.write(json.dumps(error_response, ensure_ascii=False) + "\n")
                    writer.flush()
                except Exception:
                    pass
                print(f"[CodeLens MCP] Error processing message: {e}", file=sys.stderr)

        self._shutdown()

    def _handle_signal(self, signum, frame) -> None:
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        print(f"[CodeLens MCP] Received signal {signum}, shutting down gracefully", file=sys.stderr)
        self._shutting_down = True

    def _shutdown(self) -> None:
        """Clean up resources on shutdown."""
        if self._watcher:
            try:
                self._watcher.stop()
            except Exception:
                pass
        # Shut down the hook manager (issue #47) so pending hook tasks
        # are cancelled and the worker threads exit cleanly.
        if self._hook_manager is not None:
            try:
                self._hook_manager.shutdown()
            except Exception:
                pass
            self._hook_manager = None
        elapsed = time.time() - self._start_time
        stats = self._cache.stats()
        print(
            f"[CodeLens MCP] Server shutdown: {self._request_count} requests served, "
            f"{elapsed:.1f}s uptime, cache hit rate {stats['hit_rate']:.1%}",
            file=sys.stderr
        )

    # ─── JSON-RPC Message Handling ────────────────────────

    def _handle_message(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse and dispatch a JSON-RPC message."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as e:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }

        # Validate JSON-RPC structure
        if not isinstance(message, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request: not a JSON object"}
            }

        jsonrpc = message.get("jsonrpc")
        if jsonrpc != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32600, "message": f"Invalid jsonrpc version: {jsonrpc}"}
            }

        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        # Notification (no id) — we process but don't respond
        if method and msg_id is None:
            self._dispatch_notification(method, params)
            return None

        # Request (has id) — process and respond
        if method:
            self._request_count += 1
            return self._dispatch_request(method, params, msg_id)

        # No method — invalid request
        error_response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32600, "message": "Invalid Request: missing method"},
        }
        return error_response

    def _dispatch_notification(self, method: str, params: Any) -> None:
        """Handle JSON-RPC notifications (no response expected)."""
        if method == "notifications/cancelled":
            # Client cancelled a request — we could track in-flight requests
            pass
        elif method == "notifications/initialized":
            # Client confirmed initialization
            self._initialized = True
        elif method == "notifications/message":
            # Logging message from client
            pass

    def _dispatch_request(self, method: str, params: Any, msg_id: Any) -> Dict[str, Any]:
        """Handle JSON-RPC request and return response."""
        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            elif method == "resources/list":
                result = self._handle_resources_list()
            elif method == "resources/read":
                result = self._handle_resources_read(params)
            elif method == "completion/complete":
                result = self._handle_completion(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }

    # ─── MCP Method Handlers ──────────────────────────────

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request. Returns server capabilities."""
        self._client_info = params.get("clientInfo", {})
        client_name = self._client_info.get("name", "unknown")

        print(f"[CodeLens MCP] Client connected: {client_name}", file=sys.stderr)

        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {
                    "listChanged": False
                },
                "resources": {
                    "subscribe": False,
                    "listChanged": False
                },
                "logging": {},
                "prompts": {
                    "listChanged": False
                }
            },
            "serverInfo": {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            }
        }

    def _handle_tools_list(self) -> Dict[str, Any]:
        """Handle tools/list request. Returns all CodeLens commands as MCP tools.

        Every tool's inputSchema gets a ``format`` property added with the
        enum ``[json, markdown, ai, sarif, compact]`` (issue #17). The MCP
        server always returns AI-formatted results by default; the ``format``
        parameter lets agents opt into the token-efficient ``compact`` form.
        """
        tools = []
        for cmd_name, tool_def in sorted(_TOOL_DEFINITIONS.items()):
            schema = _inject_format_enum(tool_def["parameters"])
            tools.append({
                "name": f"codelens_{cmd_name.replace('-', '_')}",
                "description": tool_def["description"],
                "inputSchema": schema,
            })

        # Also include tools for commands not in the static definitions
        # by dynamically discovering them from the command registry
        dynamic_tools = self._get_dynamic_tools()
        existing_names = {f"codelens_{k.replace('-', '_')}" for k in _TOOL_DEFINITIONS}
        for tool in dynamic_tools:
            if tool["name"] not in existing_names:
                tools.append(tool)

        return {"tools": tools}

    def _get_dynamic_tools(self) -> List[Dict[str, Any]]:
        """Dynamically generate tool definitions for any commands not in _TOOL_DEFINITIONS."""
        tools = []
        try:
            from commands import get_all_commands
            registry = get_all_commands()
            for cmd_name, cmd_info in sorted(registry.items()):
                if cmd_name in _TOOL_DEFINITIONS:
                    continue
                if cmd_name in ("watch", "serve"):
                    continue  # Skip long-running commands
                tool_name = f"codelens_{cmd_name.replace('-', '_')}"
                tools.append({
                    "name": tool_name,
                    "description": cmd_info.get("help", f"Execute the {cmd_name} command"),
                    "inputSchema": self._infer_schema_from_command(cmd_name, cmd_info),
                })
        except Exception as e:
            print(f"[CodeLens MCP] Warning: could not get dynamic tools: {e}", file=sys.stderr)
        return tools

    def _infer_schema_from_command(self, cmd_name: str, cmd_info: Dict[str, Any]) -> Dict[str, Any]:
        """Infer a JSON Schema for a command based on its argument parser.

        Includes the ``format`` enum (json/markdown/ai/sarif/compact) so
        agents can opt into compact output for any dynamically-discovered
        command (issue #17).
        """
        schema = {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Path to workspace root directory"
                }
            },
            "required": []
        }
        # Most commands require workspace
        if cmd_name not in ("ask",):
            schema["required"].append("workspace")
        # Issue #17: every tool accepts a format enum (compact = token-efficient).
        schema = _inject_format_enum(schema)
        return schema

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request. Execute a CodeLens command and return result."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Extract command name from tool name (codelens_scan -> scan)
        if not tool_name.startswith("codelens_"):
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "error",
                        "error": f"Unknown tool: {tool_name}. Tool names must start with 'codelens_'.",
                    }, ensure_ascii=False)
                }],
                "isError": True
            }

        cmd_name = tool_name[len("codelens_"):].replace("_", "-")

        # Resolve workspace
        workspace = arguments.get("workspace", "")
        if not workspace:
            workspace = self._detect_workspace()

        # Probe worktree mismatch EARLY — before any command execution.
        # Why: read commands like ``list`` / ``query`` trigger
        # ``ensure_codelens_dir(workspace)`` as a side effect of
        # loading the registry, which creates ``.codelens/`` in the
        # worktree. If we probed after execution, the worktree would
        # appear to have its own index and the mismatch would never
        # fire. Probing here caches the *pre-execution* state so the
        # banner reflects what the user actually configured, not what
        # we just created for them. (issue #66 Phase 4)
        #
        # Wrapped in try/except so a detection bug never breaks a
        # user's tool call — the banner is a nice-to-have, not a
        # critical path. The ``_get_worktree_mismatch`` method itself
        # also catches exceptions, but we double-wrap here so even a
        # bug in the caching logic doesn't escape.
        if cmd_name not in ("scan", "init"):
            try:
                self._get_worktree_mismatch(workspace)
            except Exception as exc:
                print(
                    f"[CodeLens MCP] worktree early-probe failed: {exc}",
                    file=sys.stderr,
                )

        # Check cache for non-mutating commands
        cache_key = f"cmd:{workspace}:{cmd_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
        if cmd_name not in ("scan", "init"):
            cached = self._cache.get(cache_key)
            if cached is not None:
                response = {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(cached, ensure_ascii=False)
                    }],
                    "isError": False,
                    "_cached": True
                }
                # Surface any hook notifications that have arrived since the
                # last tool call (issue #47). Even cached responses must
                # drain the queue so the agent doesn't miss warnings.
                self._attach_pending_hooks(response)
                # Attach worktree-mismatch banner (issue #66 Phase 4) on
                # read tools. Cached responses get the same banner as fresh
                # ones — the warning is a property of the workspace, not
                # the call. Mutating commands (scan, init) skip the banner
                # because they're the user's fix path.
                self._attach_worktree_banner(response, workspace)
                return response

        # Execute the command
        try:
            result = self._execute_command(cmd_name, arguments, workspace)

            # Cache the result
            if cmd_name not in ("scan", "init"):
                ttl = 60.0 if cmd_name in ("query", "symbols", "search", "list") else 300.0
                self._cache.set(cache_key, result, ttl=ttl)

            # If scan, also cache the registry in memory
            if cmd_name == "scan" and workspace:
                self._load_registry_to_memory(workspace)
                # A scan is the moment the index becomes fresh — drop
                # any cached worktree-mismatch verdict so the next read
                # tool re-probes against the new state. (If the user
                # just ran ``codelens init -i`` in the worktree, the
                # mismatch is now resolved and the banner should
                # disappear.)
                self._worktree_mismatch_cache.pop(os.path.abspath(workspace), None)

            response = {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str)
                }],
                "isError": False
            }

            # ─── Post-tool hook (issue #47) ──────────────────────────
            # Schedule the (opt-in) post_tool hook non-blocking. Even when
            # disabled this call is <1 ms — it does an enabled-flag check
            # and returns. Failures here must never break the response.
            self._maybe_run_post_tool_hook(tool_name, arguments, workspace)
            # Attach any *previously* queued hook notifications to this
            # response. (The hook we just scheduled will surface on the
            # next call — that's by design: hooks are non-blocking.)
            self._attach_pending_hooks(response)
            # Attach worktree-mismatch banner on read tools (issue
            # #66 Phase 4). Skip mutating commands (scan/init) — they're
            # the user's remediation path, not analysis calls.
            if cmd_name not in ("scan", "init"):
                self._attach_worktree_banner(response, workspace)

            return response

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            response = {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "error",
                        "command": cmd_name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    }, ensure_ascii=False)
                }],
                "isError": True
            }
            # Even on errors we drain pending hook notifications so the
            # agent doesn't lose them — issue #47 spec calls for hook
            # results to be surfaced via "next tool response".
            self._attach_pending_hooks(response)
            # And still attach the worktree banner — if the user is in
            # a misconfigured worktree, that context is more useful
            # than the error itself. The error is almost certainly
            # caused by the wrong index being loaded.
            self._attach_worktree_banner(response, workspace)
            return response

    # ─── Hook integration (issue #47) ─────────────────────

    def _get_hook_manager(self, workspace: str) -> "Optional[HookManager]":
        """Lazily create the HookManager bound to ``workspace``.

        The manager is bound to the first workspace we see and re-used for
        the lifetime of the server. ``.codelens/hooks.json`` lives at the
        workspace root, so switching workspaces would silently change the
        config — we treat the first workspace as authoritative to keep
        behavior predictable for the agent.
        """
        if not workspace:
            return None
        workspace = os.path.abspath(workspace)
        if self._hook_manager is None:
            try:
                self._hook_manager = HookManager(
                    workspace=workspace,
                    send_notification=self._send_hook_notification,
                )
                self._hook_workspace = workspace
            except Exception as exc:
                # Hook manager construction must never break the server.
                print(
                    f"[CodeLens MCP] failed to construct HookManager: {exc}",
                    file=sys.stderr,
                )
                return None
        return self._hook_manager

    def _maybe_run_post_tool_hook(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        workspace: str,
    ) -> None:
        """Fire the post_tool hook if enabled (issue #47).

        Wrapped in try/except so any failure inside the hook subsystem
        (config parse error, executor closed, hook bug) leaves the MCP
        tool response untouched.
        """
        try:
            manager = self._get_hook_manager(workspace)
            if manager is None:
                return
            manager.after_tool_call(tool_name, arguments, workspace)
        except Exception as exc:
            try:
                print(
                    f"[CodeLens MCP] post_tool hook dispatch failed: {exc}",
                    file=sys.stderr,
                )
            except Exception:
                pass

    def _attach_pending_hooks(self, response: Dict[str, Any]) -> None:
        """Drain queued hook notifications and attach them to ``response``.

        Adds a ``_hooks`` field to the response payload (in addition to
        the standard MCP fields). The MCP spec does not define this field,
        but the issue #47 spec explicitly allows hook results to be
        "added to next tool response" — agents ignore unknown top-level
        fields by spec.
        """
        try:
            manager = self._hook_manager
            if manager is None:
                return
            pending = manager.drain_pending()
            if pending:
                response["_hooks"] = pending
        except Exception:
            pass

    def _get_worktree_mismatch(self, workspace: str) -> Optional[Dict[str, Any]]:
        """Return cached worktree mismatch record for ``workspace``.

        Probes :func:`sync.worktree.detect_worktree_index_mismatch`
        exactly once per workspace per server lifetime — detection
        shells out to ``git`` twice, which is too expensive to repeat
        on every MCP tool call. The result is cached in
        ``self._worktree_mismatch_cache`` keyed by absolute workspace
        path.

        Returns ``None`` when there is no mismatch, when git is not
        available, or when the workspace is not under git control —
        callers treat ``None`` as "no banner to show".

        Returns a populated dict (with ``mismatch=True`` and the full
        mismatch record) when the workspace is a worktree using a
        foreign index. Callers attach this to the tool response so
        agents can surface the warning.

        Args:
            workspace: Absolute path to the workspace root. Empty
                strings return ``None`` without probing.

        Why this lives on the server, not on each command:
        ---------------------------------------------------
        The mismatch is a property of *where the server is running*,
        not of *which command is being called*. Caching it at the
        server level means a single git probe per workspace, shared
        across all read tools.
        """
        if not workspace:
            return None
        ws_key = os.path.abspath(workspace)
        cached = self._worktree_mismatch_cache.get(ws_key, None)
        # Note: ``None`` (default from .get) means "not yet probed".
        # A probed "no mismatch" is stored as an empty dict ``{}`` to
        # distinguish it from "never probed". This is documented at
        # the cache field declaration.
        if cached is None:
            try:
                from sync.worktree import detect_worktree_index_mismatch

                mismatch = detect_worktree_index_mismatch(ws_key)
                if mismatch and mismatch.get("mismatch"):
                    self._worktree_mismatch_cache[ws_key] = mismatch
                else:
                    # Probed, no mismatch — store sentinel to skip
                    # future git probes for this workspace.
                    self._worktree_mismatch_cache[ws_key] = {}
            except Exception as exc:
                # Detection failure must never break a tool call.
                # Log to stderr (mirrors HookManager pattern) and
                # cache the "no mismatch" sentinel so we don't retry
                # on every subsequent call.
                print(
                    f"[CodeLens MCP] worktree mismatch detection failed: {exc}",
                    file=sys.stderr,
                )
                self._worktree_mismatch_cache[ws_key] = {}
        result = self._worktree_mismatch_cache.get(ws_key)
        # Return the populated dict only if it has ``mismatch=True``.
        if result and result.get("mismatch"):
            return result
        return None

    def _attach_worktree_banner(self, response: Dict[str, Any], workspace: str) -> None:
        """Attach a worktree-mismatch banner to ``response`` if needed.

        Adds a ``_worktree_warning`` field to the response payload.
        The field is a dict with the full mismatch record plus a
        human-readable ``banner`` string. Agents that know about the
        field surface the banner; agents that don't ignore it (per
        MCP spec — unknown top-level fields are ignored).

        Why a separate field rather than prepending to ``content``:
        Prepending text to the ``content`` array would corrupt the
        JSON payload that agents parse out of the second content
        item. A top-level field keeps the JSON response intact while
        still surfacing the warning prominently.
        """
        try:
            mismatch = self._get_worktree_mismatch(workspace)
            if not mismatch:
                return
            from sync.worktree import format_worktree_banner

            response["_worktree_warning"] = {
                "banner": format_worktree_banner(mismatch),
                "mismatch": mismatch,
            }
        except Exception:
            # Banner attachment must never break a tool response.
            pass

    def _send_hook_notification(self, notification: Dict[str, Any]) -> None:
        """Push a hook notification to the agent via stdout JSON-RPC.

        The MCP spec allows the server to send unsolicited
        ``notifications/message`` payloads at any time. We write them
        inline to stdout (the same channel used for responses) — agents
        route them by ``method``.
        """
        try:
            payload = json.dumps(notification, ensure_ascii=False)
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
        except Exception:
            # If stdout is closed (e.g. during shutdown), silently drop.
            pass


    def _handle_resources_list(self) -> Dict[str, Any]:
        """Handle resources/list request. Expose codebase registries as resources."""
        resources = []
        for workspace in self._workspace_registries:
            ws_name = os.path.basename(workspace)
            resources.append({
                "uri": f"codelens://registry/{ws_name}/frontend",
                "name": f"Frontend Registry: {ws_name}",
                "description": "CodeLens frontend registry (CSS classes, IDs, references)",
                "mimeType": "application/json"
            })
            resources.append({
                "uri": f"codelens://registry/{ws_name}/backend",
                "name": f"Backend Registry: {ws_name}",
                "description": "CodeLens backend registry (functions, call graph, edges)",
                "mimeType": "application/json"
            })

        # Always include a template resource
        resources.append({
            "uri": "codelens://registry/{workspace}/{domain}",
            "name": "Registry Template",
            "description": "Template for accessing any workspace registry. Replace {workspace} and {domain}.",
            "mimeType": "application/json"
        })

        return {"resources": resources}

    def _handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request. Return registry data."""
        uri = params.get("uri", "")

        if not uri.startswith("codelens://registry/"):
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": f"Unknown resource URI: {uri}"}, ensure_ascii=False)
                }],
                "isError": True
            }

        parts = uri[len("codelens://registry/"):].split("/")
        if len(parts) < 2:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": "Invalid resource URI format"}, ensure_ascii=False)
                }],
                "isError": True
            }

        ws_name, domain = parts[0], parts[1]

        # Find workspace by basename
        workspace = None
        for ws in self._workspace_registries:
            if os.path.basename(ws) == ws_name:
                workspace = ws
                break

        if not workspace:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": f"Workspace not found: {ws_name}"}, ensure_ascii=False)
                }],
                "isError": True
            }

        registry_data = self._workspace_registries.get(workspace, {})
        domain_data = registry_data.get(domain, {})

        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(domain_data, ensure_ascii=False, default=str)
            }]
        }

    def _handle_completion(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle completion/complete request. Provide completions for tool arguments."""
        ref = params.get("ref", {})
        arg_name = ref.get("name", "")
        completions = []

        if arg_name == "workspace":
            # Suggest known workspaces
            for ws in self._workspace_registries:
                completions.append({"value": ws, "label": os.path.basename(ws)})

        return {
            "completion": {
                "values": completions,
                "total": len(completions),
                "hasMore": False
            }
        }

    # ─── Command Execution ────────────────────────────────

    def _execute_command(self, cmd_name: str, arguments: Dict[str, Any], workspace: str) -> Dict[str, Any]:
        """Execute a CodeLens command by name with the given arguments.

        Results are formatted in AI mode (normalized schema) by default. If
        the caller passes ``format='compact'`` (issue #17), the result is
        compacted via :mod:`formatters.compact` — single-char keys,
        abbreviated types, no null fields — to cut token usage 40-70%.
        """
        from commands import get_all_commands
        from formatters import format_output

        if self._command_registry is None:
            self._command_registry = get_all_commands()

        cmd_info = self._command_registry.get(cmd_name)
        if cmd_info is None:
            return {
                "status": "error",
                "error": f"Unknown command: {cmd_name}",
                "available_commands": sorted(self._command_registry.keys())
            }

        # Issue #58, Phase 1: validate any agent-supplied ``file`` /
        # ``path`` argument stays inside the workspace. This is the
        # MCP-side enforcement point — the most agent-driven read
        # surface. Refusals return a structured error so the agent
        # can self-correct instead of getting an opaque crash.
        path_error = self._validate_path_args(arguments, workspace)
        if path_error is not None:
            return path_error

        # Build an args namespace from the arguments dict
        args = _ArgsNamespace(arguments, workspace)

        # Execute the command
        result = cmd_info["execute"](args, workspace)

        # Format the result. Default is AI mode; compact mode returns the
        # compacted dict so the JSON-RPC transport layer can serialize it.
        fmt = arguments.get("format") or "ai"
        if fmt == "compact" and isinstance(result, dict):
            from formatters.compact import compact_dict
            return compact_dict(result, workspace)
        if isinstance(result, dict):
            from formatters import _normalize_to_ai
            return _normalize_to_ai(result, cmd_name)

        return {"status": "ok", "items": [result]}

    # Argument names that agents can use to point CodeLens at a file.
    # Kept narrow on purpose — only arguments that directly translate
    # to a filesystem read are validated here. ``workspace`` itself is
    # resolved separately by the MCP server's workspace resolution
    # layer and is NOT agent-controlled per-call.
    _PATH_LIKE_ARGS = frozenset({"file", "path", "file_path"})

    def _validate_path_args(
        self,
        arguments: Dict[str, Any],
        workspace: str,
    ) -> Optional[Dict[str, Any]]:
        """Validate agent-supplied path-like arguments stay in ``workspace``.

        Returns ``None`` if all path-like args are safe (or absent),
        otherwise returns a structured error dict suitable for direct
        return to the MCP client.

        Phase 1 scope: only refuses paths that lexically/symlink-escape
        the workspace. Does NOT refuse relative paths (those are
        resolved against ``workspace`` by the commands themselves,
        which is the desired behavior).
        """
        if not workspace:
            return None
        try:
            from security.path_traversal import (
                PathRefusalError,
                resolve_path_within_project,
            )
        except ImportError:
            # If the security module isn't available, degrade to
            # pre-issue-#58 behavior rather than blocking all calls.
            return None

        for arg_name in self._PATH_LIKE_ARGS:
            if arg_name not in arguments:
                continue
            raw = arguments[arg_name]
            if not isinstance(raw, str) or not raw:
                continue
            # Resolve relative paths against the workspace before
            # checking — this matches how commands consume them.
            candidate = raw if os.path.isabs(raw) else os.path.join(workspace, raw)
            try:
                resolve_path_within_project(workspace, candidate)
            except PathRefusalError as exc:
                return {
                    "status": "error",
                    "error": "path_refusal",
                    "message": str(exc),
                    "argument": arg_name,
                    "value": raw,
                    "workspace": workspace,
                    "suggestion": (
                        "Use a path that resolves inside the workspace root. "
                        "Relative paths are resolved against the workspace."
                    ),
                }
        return None

    def _detect_workspace(self) -> str:
        """Auto-detect workspace from current directory."""
        try:
            from codelens import resolve_workspace
            return resolve_workspace()
        except Exception:
            return os.getcwd()

    def _load_registry_to_memory(self, workspace: str) -> None:
        """Load registry files into memory for fast access."""
        try:
            from registry import load_frontend_registry, load_backend_registry
            workspace = os.path.abspath(workspace)
            self._workspace_registries[workspace] = {
                "frontend": load_frontend_registry(workspace),
                "backend": load_backend_registry(workspace),
            }
            # Cache the registry too
            self._cache.set(f"registry:{workspace}:frontend", self._workspace_registries[workspace]["frontend"], ttl=0)
            self._cache.set(f"registry:{workspace}:backend", self._workspace_registries[workspace]["backend"], ttl=0)
            print(f"[CodeLens MCP] Registry loaded into memory: {workspace}", file=sys.stderr)
        except Exception as e:
            print(f"[CodeLens MCP] Failed to load registry: {e}", file=sys.stderr)

    # ─── File Watching ────────────────────────────────────

    def start_watcher(self, workspace: str) -> None:
        """Start background file watcher for a workspace."""
        if self._watcher is not None:
            return

        workspace = os.path.abspath(workspace)
        print(f"[CodeLens MCP] Starting file watcher for {workspace}", file=sys.stderr)

        def _watch_loop():
            """Background thread: poll for file changes and invalidate cache."""
            from commands.watch import _watch_polling
            # Use the polling watcher's change detection
            last_mtimes: Dict[str, float] = {}
            from utils import DEFAULT_IGNORE_DIRS
            _WATCH_EXTENSIONS = frozenset({
                '.html', '.htm', '.css', '.scss', '.less', '.sass',
                '.js', '.jsx', '.ts', '.tsx', '.rs', '.py', '.vue', '.svelte',
            })

            # Initial scan of mtimes
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in _WATCH_EXTENSIONS:
                        filepath = os.path.join(root, filename)
                        try:
                            last_mtimes[filepath] = os.path.getmtime(filepath)
                        except OSError:
                            pass

            # Poll loop
            while not self._shutting_down:
                time.sleep(2)
                changed = False
                for filepath in list(last_mtimes.keys()):
                    try:
                        current = os.path.getmtime(filepath)
                        if current != last_mtimes[filepath]:
                            last_mtimes[filepath] = current
                            changed = True
                    except OSError:
                        del last_mtimes[filepath]
                        changed = True

                if changed:
                    # Invalidate cache and reload registry
                    self._cache.invalidate_workspace(workspace)
                    self._load_registry_to_memory(workspace)
                    print(f"[CodeLens MCP] Files changed, registry reloaded and cache invalidated", file=sys.stderr)

        self._watcher_thread = threading.Thread(target=_watch_loop, daemon=True)
        self._watcher_thread.start()

    # ─── Server Stats ─────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return server statistics."""
        return {
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "requests_served": self._request_count,
            "workspaces_loaded": list(self._workspace_registries.keys()),
            "cache": self._cache.stats(),
            "initialized": self._initialized,
            "watch_active": self._watcher_thread is not None and self._watcher_thread.is_alive(),
        }


# ─── Args Namespace Helper ────────────────────────────────────────────

class _ArgsNamespace:
    """Simple namespace that mimics argparse.Namespace for command execution.

    Maps MCP tool arguments to the format expected by CodeLens command execute() functions.
    Provides attribute access to the arguments dict with sensible defaults.
    """

    def __init__(self, arguments: Dict[str, Any], workspace: str):
        self._arguments = arguments
        self.workspace = workspace

        # Map common argument names
        for key, value in arguments.items():
            # Convert kebab-case to snake_case for Python attribute access
            attr_name = key.replace("-", "_")
            if not hasattr(self, attr_name):
                setattr(self, attr_name, value)

        # Ensure common attributes have defaults
        if not hasattr(self, 'name'):
            self.name = arguments.get('name', arguments.get('question', ''))
        if not hasattr(self, 'pattern'):
            self.pattern = arguments.get('pattern', '')
        if not hasattr(self, 'file'):
            self.file = arguments.get('file', None)
        if not hasattr(self, 'domain'):
            self.domain = arguments.get('domain', None)
        if not hasattr(self, 'filter_type'):
            self.filter_type = arguments.get('filter', 'all')
        if not hasattr(self, 'limit'):
            self.limit = arguments.get('limit', None)
        if not hasattr(self, 'offset'):
            self.offset = arguments.get('offset', 0)
        if not hasattr(self, 'fuzzy'):
            self.fuzzy = arguments.get('fuzzy', False)
        if not hasattr(self, 'incremental'):
            self.incremental = arguments.get('incremental', False)
        if not hasattr(self, 'max_files'):
            self.max_files = arguments.get('max_files', 5000)
        if not hasattr(self, 'top'):
            self.top = arguments.get('top', None)
        if not hasattr(self, 'max_tokens'):
            self.max_tokens = arguments.get('max_tokens', None)
        if not hasattr(self, 'lite'):
            self.lite = arguments.get('lite', False)
        if not hasattr(self, 'format'):
            self.format = 'ai'  # Always AI format in MCP mode
        if not hasattr(self, 'focus'):
            self.focus = arguments.get('focus', 'all')
        if not hasattr(self, 'detail'):
            self.detail = arguments.get('detail', 'standard')
        if not hasattr(self, 'skip_scan'):
            self.skip_scan = arguments.get('skip_scan', False)
        if not hasattr(self, 'max_items'):
            self.max_items = arguments.get('max_items', 15)
        if not hasattr(self, 'timeout'):
            self.timeout = arguments.get('timeout', 300)
        if not hasattr(self, 'severity'):
            self.severity = arguments.get('severity', None)
        if not hasattr(self, 'categories'):
            self.categories = arguments.get('categories', None)
        if not hasattr(self, 'sort_by'):
            self.sort_by = arguments.get('sort', None)
        if not hasattr(self, 'threshold'):
            self.threshold = arguments.get('threshold', None)
        if not hasattr(self, 'direction'):
            self.direction = arguments.get('direction', 'both')
        if not hasattr(self, 'max_depth'):
            self.max_depth = arguments.get('max_depth', 5)
        if not hasattr(self, 'exclude_tests'):
            self.exclude_tests = arguments.get('exclude_tests', False)
        if not hasattr(self, 'debounce'):
            self.debounce = arguments.get('debounce', 0.5)
        if not hasattr(self, 'all'):
            self.all = arguments.get('all', False)

    def __repr__(self):
        return f"_ArgsNamespace(workspace={self.workspace!r}, args={self._arguments!r})"


# ─── MCP Hook Manager (issue #47, Phase 1: post_tool) ────────────────


class HookManager:
    """Manages opt-in MCP hooks that auto-trigger scan/check after AI writes.

    Implements Phase 1 of issue #47. The manager:

    1. Reads ``.codelens/hooks.json`` from the workspace on construction,
       creating the file with default content (all hooks ``enabled: false``)
       if it does not exist yet.
    2. After every MCP tool call that *might* modify a file, the
       :meth:`after_tool_call` method schedules the ``post_tool`` hook
       non-blocking in a :class:`ThreadPoolExecutor`. The hook itself is
       implemented in :mod:`mcp_hooks.post_tool`.
    3. When the hook surfaces a new critical/high finding, the manager
       enqueues an MCP ``notifications/message`` payload that the caller
       can either emit immediately via stdout or attach to the *next*
       ``tools/call`` response as a ``_hooks`` field.

    Design constraints (issue #47):

    - **Default disabled**: every hook defaults to ``enabled: false`` — the
      user must opt in explicitly via ``.codelens/hooks.json``.
    - **Non-blocking**: ``after_tool_call`` returns in <<1 ms (it only
      schedules the executor). Hook failures are caught, logged to stderr,
      and never propagated to the caller. The MCP server stays alive.
    - **Performance target**: <500 ms added latency to the original tool
      call. Because the hook runs entirely off the request thread, the
      only synchronous cost is argument inspection that decides whether
      to fire the hook at all.

    The class is intentionally usable in isolation (no MCPServer required)
    so unit tests can exercise config loading, hook dispatch, and
    notification buffering without booting the full server.
    """

    #: Path of the hooks config file, relative to the workspace root.
    CONFIG_PATH = os.path.join(".codelens", "hooks.json")

    def __init__(
        self,
        workspace: Optional[str] = None,
        max_workers: int = 2,
        send_notification: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """Create a hook manager bound to ``workspace``.

        Parameters
        ----------
        workspace:
            Workspace root used to locate ``.codelens/hooks.json`` and to
            pass through to the hook implementation. Falls back to the
            current working directory if ``None``.
        max_workers:
            Size of the underlying ThreadPoolExecutor. Default 2 is enough
            for the post_tool hook — hooks share the pool.
        send_notification:
            Optional callback invoked with each MCP notification dict the
            hook produces. The MCPServer wires this to its stdout writer so
            notifications reach the agent in real time. If ``None``, the
            notifications are buffered in :attr:`_pending` and surfaced via
            :meth:`drain_pending` (useful for tests and for the
            "attach to next response" mode).
        """
        self._workspace = workspace or os.getcwd()
        self._send_notification = send_notification
        self._lock = threading.Lock()
        self._pending: List[Dict[str, Any]] = []
        self._executor: Optional[ThreadPoolExecutor] = None
        try:
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="codelens-hook",
            )
        except RuntimeError:
            # Interpreter shutdown in progress — leave executor as None,
            # hooks will be no-ops. Server is going down anyway.
            self._executor = None
        self._config: Dict[str, Any] = self._load_or_create_config(self._workspace)

    # ─── Config ────────────────────────────────────────────

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """Return a fresh deep copy of the default (all-disabled) config."""
        from mcp_hooks.post_tool import DEFAULT_CONFIG

        # json round-trip for a robust deep copy across Python versions.
        return json.loads(json.dumps(DEFAULT_CONFIG))

    @classmethod
    def _load_or_create_config(cls, workspace: str) -> Dict[str, Any]:
        """Load ``.codelens/hooks.json`` from ``workspace``.

        If the file does not exist, create it with the default config
        (all hooks disabled — opt-in). If the file exists but is
        unreadable or malformed, fall back to defaults silently so a
        corrupted config never breaks the MCP server.

        Missing per-hook keys are backfilled from the defaults so the rest
        of the manager can rely on the schema being complete.
        """
        default = cls._default_config()
        if not workspace or not os.path.isdir(workspace):
            return default
        config_path = os.path.join(workspace, cls.CONFIG_PATH)
        try:
            if not os.path.isfile(config_path):
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2, ensure_ascii=False)
                return default

            with open(config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return default

            # Merge: start from defaults so newly-added hooks appear.
            merged = default
            hooks_block = loaded.get("hooks")
            if isinstance(hooks_block, dict):
                merged_hooks = dict(default.get("hooks", {}))
                for name, cfg in hooks_block.items():
                    if not isinstance(cfg, dict):
                        continue
                    base = dict(merged_hooks.get(name, {"enabled": False}))
                    base.update(cfg)
                    merged_hooks[name] = base
                merged = dict(default)
                merged["hooks"] = merged_hooks
            return merged
        except (OSError, json.JSONDecodeError, TypeError):
            return default

    def reload_config(self) -> None:
        """Re-read the config file from disk (call after the user edits it)."""
        with self._lock:
            self._config = self._load_or_create_config(self._workspace)

    @property
    def config(self) -> Dict[str, Any]:
        """Snapshot of the merged config dict."""
        with self._lock:
            # Return a shallow copy so callers can't mutate the live view.
            return dict(self._config)

    @property
    def workspace(self) -> str:
        return self._workspace

    def is_enabled(self, hook_name: str) -> bool:
        """Return ``True`` only when ``hook_name`` is explicitly enabled.

        Defaults to ``False`` for unknown hooks — opt-in.
        """
        with self._lock:
            hooks_block = self._config.get("hooks", {})
        if not isinstance(hooks_block, dict):
            return False
        cfg = hooks_block.get(hook_name, {})
        if not isinstance(cfg, dict):
            return False
        # Only an explicit truthy bool enables a hook.
        return bool(cfg.get("enabled", False))

    def severity_threshold(self, hook_name: str) -> str:
        """Return the configured severity threshold for ``hook_name``.

        Falls back to ``"high"`` for unknown hooks / malformed entries —
        matches the issue #47 default schema.
        """
        with self._lock:
            hooks_block = self._config.get("hooks", {})
        if not isinstance(hooks_block, dict):
            return "high"
        cfg = hooks_block.get(hook_name, {})
        if not isinstance(cfg, dict):
            return "high"
        sev = cfg.get("severity_threshold", "high")
        if not isinstance(sev, str) or not sev.strip():
            return "high"
        return sev.strip().lower()

    # ─── Hook dispatch ────────────────────────────────────

    def after_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        workspace: Optional[str] = None,
        on_complete: Optional[Callable[["PostToolHookResult"], None]] = None,
    ) -> None:
        """Schedule the post_tool hook non-blocking.

        This is the *only* method :class:`MCPServer` calls after every
        tool call. It never raises: any internal error is logged to stderr
        and swallowed so the MCP server stays alive.

        ``on_complete`` is invoked from the worker thread once the hook
        finishes (success or failure). Tests use it to wait for the
        async hook deterministically.

        Parameters
        ----------
        tool_name:
            The MCP tool name (e.g. ``codelens_query``).
        arguments:
            The MCP tool call arguments dict (``params.arguments``).
            Snapshotted before submission so later mutations don't race.
        workspace:
            Optional workspace override. Defaults to the manager's
            workspace.
        on_complete:
            Optional callback invoked with the :class:`PostToolHookResult`
            when the hook finishes. Failures in the callback are swallowed.
        """
        if not self.is_enabled("post_tool"):
            # Hook disabled — fast path with zero side effects.
            return
        if self._executor is None:
            # Server is shutting down — silently no-op.
            return
        ws = workspace or self._workspace or ""
        if not ws:
            return
        if not isinstance(arguments, dict):
            arguments = {}
        # Shallow-copy arguments so the worker thread sees a stable snapshot
        # even if the caller mutates the dict after we return.
        args_snapshot = dict(arguments)
        severity = self.severity_threshold("post_tool")
        try:
            self._executor.submit(
                self._run_post_tool_blocking,
                tool_name,
                args_snapshot,
                ws,
                severity,
                on_complete,
            )
        except RuntimeError:
            # Executor was shut down between the None check and submit.
            pass

    def _run_post_tool_blocking(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        workspace: str,
        severity_threshold: str,
        on_complete: Optional[Callable[["PostToolHookResult"], None]],
    ) -> None:
        """Worker entry point — runs the hook and buffers/forwards the result.

        Wrapped in a try/except so a bug in the hook implementation can
        never take down the executor thread (which would leak the pool).
        """
        try:
            from mcp_hooks.post_tool import run_post_tool_hook

            result = run_post_tool_hook(arguments, workspace, severity_threshold)
        except Exception as exc:  # pragma: no cover — defensive guard
            try:
                print(
                    f"[CodeLens MCP] post_tool hook crashed: {exc}",
                    file=sys.stderr,
                )
            except Exception:
                pass
            return

        # Surface critical/high findings to the agent.
        notification = self._result_to_notification(result, tool_name)
        if notification is not None:
            self._emit_notification(notification)

        if on_complete is not None:
            try:
                on_complete(result)
            except Exception:
                # Callback failures must not break the worker thread.
                pass

    def _result_to_notification(
        self,
        result: "PostToolHookResult",
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Build an MCP ``notifications/message`` payload from a hook result.

        Returns ``None`` when the hook did not surface anything worth
        notifying the agent about (no critical/high findings, hook did
        not trigger, or hook errored without findings).
        """
        if not getattr(result, "triggered", False):
            return None
        if not (result.critical_count or result.high_count):
            return None
        return {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": "warning",
                "data": {
                    "source": "codelens.post_tool_hook",
                    "tool": tool_name,
                    "file": result.file_path,
                    "workspace": result.workspace,
                    "severity_threshold": result.severity_threshold,
                    "critical_count": result.critical_count,
                    "high_count": result.high_count,
                    "message": result.message,
                    "elapsed_ms": round(result.elapsed_ms, 2),
                    "error": result.error,
                },
            },
        }

    def _emit_notification(self, notification: Dict[str, Any]) -> None:
        """Either forward the notification via the callback or buffer it."""
        if self._send_notification is not None:
            try:
                self._send_notification(notification)
                return
            except Exception:
                # Forwarding failed — fall through and buffer so the
                # notification still surfaces via the next tool response.
                pass
        with self._lock:
            self._pending.append(notification)

    # ─── Pending notification queue ───────────────────────

    def drain_pending(self) -> List[Dict[str, Any]]:
        """Atomically return and clear all queued hook notifications."""
        with self._lock:
            pending = list(self._pending)
            self._pending.clear()
        return pending

    def pending_notifications(self) -> List[Dict[str, Any]]:
        """Return a copy of the queued hook notifications (does not clear)."""
        with self._lock:
            return list(self._pending)

    # ─── Lifecycle ────────────────────────────────────────

    def shutdown(self) -> None:
        """Cancel queued hook tasks and shut down the executor.

        Called by :class:`MCPServer` during graceful shutdown.
        """
        executor = self._executor
        self._executor = None
        if executor is None:
            return
        try:
            # cancel_futures added in Python 3.9 — fall back gracefully.
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # pragma: no cover — Python <3.9 fallback
            executor.shutdown(wait=False)


# ─── HTTP/SSE Transport (Optional) ────────────────────────────────────

def start_http_server(mcp_server: MCPServer, port: int = 8080) -> None:
    """Start an HTTP server with SSE transport for remote MCP clients.

    This is an optional transport layer in addition to the default stdio transport.
    It provides:
    - GET /sse — SSE endpoint for server-to-client messages
    - POST /message — Client-to-server message endpoint
    - GET /health — Health check endpoint

    Uses only stdlib (http.server) — no external dependencies.
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    class MCPHTTPHandler(BaseHTTPRequestHandler):
        """HTTP handler for MCP JSON-RPC over HTTP/SSE."""

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)

            if parsed.path == "/sse":
                self._handle_sse()
            elif parsed.path == "/health":
                self._handle_health()
            else:
                self.send_error(404, "Not Found")

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)

            if parsed.path == "/message":
                self._handle_message()
            else:
                self.send_error(404, "Not Found")

        def _handle_sse(self):
            """Handle SSE connection for server-to-client messages."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Send initial endpoint event
            endpoint = f"http://localhost:{self.server.server_port}/message"
            self.wfile.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
            self.wfile.flush()

            # Keep connection alive with heartbeat
            try:
                while not mcp_server._shutting_down:
                    time.sleep(5)
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception:
                pass

        def _handle_message(self):
            """Handle incoming JSON-RPC message via HTTP POST."""
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            response = mcp_server._handle_message(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            if response is not None:
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode())
            else:
                self.wfile.write(b'{"jsonrpc":"2.0","result":{}}')

        def _handle_health(self):
            """Handle health check endpoint."""
            stats = mcp_server.get_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode())

        def log_message(self, format, *args):
            """Log HTTP requests to stderr (not stdout)."""
            print(f"[CodeLens MCP HTTP] {format % args}", file=sys.stderr)

    server = HTTPServer(("0.0.0.0", port), MCPHTTPHandler)
    print(f"[CodeLens MCP] HTTP/SSE server listening on port {port}", file=sys.stderr)

    # Run in a separate thread so it doesn't block stdin reading
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()

    return server


# ─── MCP Config Generator ─────────────────────────────────────────────

def generate_mcp_config(codelens_path: Optional[str] = None) -> Dict[str, Any]:
    """Generate MCP client configuration for popular AI tools.

    Returns configuration for:
    - Claude Desktop (claude_desktop_config.json)
    - Cursor (.cursor/mcp.json)
    - VS Code (settings.json)
    - Continue.dev (config.json)
    """
    if codelens_path is None:
        codelens_path = os.path.abspath(os.path.join(SCRIPT_DIR, "codelens.py"))

    base_config = {
        "command": sys.executable,
        "args": [codelens_path, "serve"],
        "env": {
            "CODELENS_AI_MODE": "1"
        }
    }

    return {
        "claude_desktop": {
            "config_file": "~/Library/Application Support/Claude/claude_desktop_config.json",
            "config": {
                "mcpServers": {
                    "codelens": base_config
                }
            }
        },
        "cursor": {
            "config_file": ".cursor/mcp.json",
            "config": {
                "mcpServers": {
                    "codelens": base_config
                }
            }
        },
        "vscode": {
            "config_file": ".vscode/settings.json",
            "config": {
                "mcp": {
                    "servers": {
                        "codelens": {
                            "url": "http://localhost:8080/sse",
                            "transport": "sse"
                        }
                    }
                }
            }
        },
        "continue_dev": {
            "config_file": "~/.continue/config.json",
            "config": {
                "mcpServers": [
                    {
                        "name": "codelens",
                        **base_config
                    }
                ]
            }
        },
        "raw": base_config
    }


# ─── Main Entry Point ─────────────────────────────────────────────────

def run_mcp_server(watch: bool = False, port: Optional[int] = None) -> None:
    """Start the CodeLens MCP server.

    Args:
        watch: Enable file watching for auto-updates
        port: Optional HTTP/SSE port (in addition to stdio)
    """
    server = MCPServer(watch=watch)

    # Auto-detect workspace and warm cache if possible
    workspace = server._detect_workspace()
    if workspace and os.path.isdir(os.path.join(workspace, ".codelens")):
        server._load_registry_to_memory(workspace)
        print(f"[CodeLens MCP] Auto-warmed registry cache for {workspace}", file=sys.stderr)

    # Start file watcher if requested
    if watch and workspace:
        server.start_watcher(workspace)

    # Start HTTP/SSE transport if requested
    if port:
        start_http_server(server, port)

    # Start stdio transport (main loop)
    server.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CodeLens MCP Server")
    parser.add_argument("--watch", action="store_true", help="Enable file watching")
    parser.add_argument("--port", type=int, default=None, help="HTTP/SSE port (optional)")
    args = parser.parse_args()
    run_mcp_server(watch=args.watch, port=args.port)

#!/usr/bin/env python3
"""
CodeLens MCP Server — Model Context Protocol server for AI agent integration.

Implements the MCP specification (2025-03-26) over stdio (JSON-RPC 2.0).
Provides persistent server mode with in-memory registry caching, sub-millisecond
query latency after initial scan, and automatic tool discovery for all 45+ CodeLens commands.

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
from typing import Any, Dict, List, Optional, Tuple
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
    "validate": {
        "description": "Validate registry against file system. Detect stale registry entries.",
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
                "format": {
                    "type": "string",
                    "description": "Output format (default: json)",
                    "default": "json"
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
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32600, "message": "Invalid Request: missing method"}
        }

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

        # Check cache for non-mutating commands
        cache_key = f"cmd:{workspace}:{cmd_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
        if cmd_name not in ("scan", "init"):
            cached = self._cache.get(cache_key)
            if cached is not None:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(cached, ensure_ascii=False)
                    }],
                    "isError": False,
                    "_cached": True
                }

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

            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str)
                }],
                "isError": False
            }

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {
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

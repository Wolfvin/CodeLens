"""
SARIF Output Formatter for CodeLens — Static Analysis Results Interchange Format.

Generates SARIF v2.1.0 compliant output for integration with:
- GitHub Advanced Security (code scanning alerts)
- Azure DevOps
- VS Code SARIF Viewer
- SonarQube SARIF import
- Any SARIF-compatible tool

SARIF Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

Maps CodeLens finding categories to SARIF result level:
- critical → "error"
- high     → "error"
- medium   → "warning"
- low      → "note"
- info     → "note"

Each CodeLens command maps to a SARIF rule with:
- Unique rule ID (e.g., "codelens/secrets/api-key")
- Help URI pointing to relevant documentation
- Default configuration (level, rank)
"""

import json
import os
import time
from typing import Any, Dict, List, Optional


# ─── SARIF Version ──────────────────────────────────────────

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

# ─── CodeLens → SARIF Mapping ───────────────────────────────

SEVERITY_TO_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
    "warning": "warning",
    "error": "error",
}

SEVERITY_TO_RANK = {
    "critical": 90.0,
    "high": 70.0,
    "medium": 50.0,
    "low": 30.0,
    "info": 10.0,
    "warning": 50.0,
    "error": 70.0,
}

# Rule definitions for each CodeLens command
COMMAND_RULES = {
    "secrets": {
        "id_prefix": "codelens/secrets",
        "name": "CodeLens Secrets Detection",
        "short_description": "Detects hardcoded secrets, API keys, and credentials",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/secrets.md",
        "categories": {
            "api_key": {"id": "codelens/secrets/api-key", "description": "Hardcoded API key detected"},
            "token": {"id": "codelens/secrets/token", "description": "Hardcoded token detected"},
            "secret_key": {"id": "codelens/secrets/secret-key", "description": "Hardcoded secret key detected"},
            "password": {"id": "codelens/secrets/password", "description": "Hardcoded password detected"},
            "private_key": {"id": "codelens/secrets/private-key", "description": "Hardcoded private key detected"},
            "connection_string": {"id": "codelens/secrets/connection-string", "description": "Hardcoded connection string detected"},
            "webhook": {"id": "codelens/secrets/webhook", "description": "Hardcoded webhook URL detected"},
        }
    },
    "dead-code": {
        "id_prefix": "codelens/dead-code",
        "name": "CodeLens Dead Code Detection",
        "short_description": "Detects unreachable, unused, and dead code",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/dead-code.md",
        "categories": {
            "unreachable": {"id": "codelens/dead-code/unreachable", "description": "Unreachable code detected"},
            "unused_variable": {"id": "codelens/dead-code/unused-variable", "description": "Unused variable detected"},
            "unused_import": {"id": "codelens/dead-code/unused-import", "description": "Unused import detected"},
            "zombie_css": {"id": "codelens/dead-code/zombie-css", "description": "Unused CSS class detected"},
            "unused_export": {"id": "codelens/dead-code/unused-export", "description": "Unused export detected"},
        }
    },
    "smell": {
        "id_prefix": "codelens/smell",
        "name": "CodeLens Code Smell Detection",
        "short_description": "Detects code smells and quality issues",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/smell.md",
        "categories": {
            "long_fn": {"id": "codelens/smell/long-function", "description": "Long function detected"},
            "deep_nesting": {"id": "codelens/smell/deep-nesting", "description": "Deep nesting detected"},
            "many_params": {"id": "codelens/smell/many-params", "description": "Too many parameters detected"},
            "dup_code": {"id": "codelens/smell/duplicate-code", "description": "Duplicate code detected"},
            "god_class": {"id": "codelens/smell/god-class", "description": "God class detected"},
        }
    },
    "complexity": {
        "id_prefix": "codelens/complexity",
        "name": "CodeLens Complexity Analysis",
        "short_description": "Computes cyclomatic and cognitive complexity",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/complexity.md",
        "categories": {
            "high_cyclomatic": {"id": "codelens/complexity/high-cyclomatic", "description": "High cyclomatic complexity"},
            "high_cognitive": {"id": "codelens/complexity/high-cognitive", "description": "High cognitive complexity"},
        }
    },
    "debug-leak": {
        "id_prefix": "codelens/debug-leak",
        "name": "CodeLens Debug Leak Detection",
        "short_description": "Detects leftover debug code in production",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/debug-leak.md",
        "categories": {
            "console_log": {"id": "codelens/debug-leak/console-log", "description": "Console.log statement detected"},
            "print_statement": {"id": "codelens/debug-leak/print", "description": "Print statement detected"},
            "debugger": {"id": "codelens/debug-leak/debugger", "description": "Debugger statement detected"},
            "todo_fixme": {"id": "codelens/debug-leak/todo-fixme", "description": "TODO/FIXME marker detected"},
            "commented_code": {"id": "codelens/debug-leak/commented-code", "description": "Commented-out code detected"},
        }
    },
    "circular": {
        "id_prefix": "codelens/circular",
        "name": "CodeLens Circular Dependency Detection",
        "short_description": "Detects circular import/dependency cycles",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/circular.md",
        "categories": {
            "import_cycle": {"id": "codelens/circular/import-cycle", "description": "Circular import dependency detected"},
            "function_cycle": {"id": "codelens/circular/function-cycle", "description": "Circular function call detected"},
        }
    },
    "perf-hint": {
        "id_prefix": "codelens/perf-hint",
        "name": "CodeLens Performance Hints",
        "short_description": "Detects performance anti-patterns",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/perf-hint.md",
        "categories": {
            "n_plus_1": {"id": "codelens/perf-hint/n-plus-1", "description": "N+1 query pattern detected"},
            "sync_blocking": {"id": "codelens/perf-hint/sync-blocking", "description": "Blocking sync operation detected"},
            "inefficient_loop": {"id": "codelens/perf-hint/inefficient-loop", "description": "Inefficient loop pattern detected"},
        }
    },
    "taint": {
        "id_prefix": "codelens/taint",
        "name": "CodeLens Taint Analysis",
        "short_description": "Tracks tainted data flow from sources to sinks",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/taint.md",
        "categories": {
            "sql_injection": {"id": "codelens/taint/sql-injection", "description": "SQL injection vulnerability detected"},
            "command_injection": {"id": "codelens/taint/command-injection", "description": "Command injection vulnerability detected"},
            "path_traversal": {"id": "codelens/taint/path-traversal", "description": "Path traversal vulnerability detected"},
            "xss": {"id": "codelens/taint/xss", "description": "Cross-site scripting vulnerability detected"},
            "ssrf": {"id": "codelens/taint/ssrf", "description": "Server-side request forgery detected"},
        }
    },
    "dataflow": {
        "id_prefix": "codelens/dataflow",
        "name": "CodeLens Data Flow Analysis",
        "short_description": "Tracks data flow from sources to sinks",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/dataflow.md",
        "categories": {
            "tainted_source": {"id": "codelens/dataflow/tainted-source", "description": "Tainted data from source reaches sink"},
        }
    },
    "vuln-scan": {
        "id_prefix": "codelens/vuln-scan",
        "name": "CodeLens Vulnerability Scanner",
        "short_description": "Scans dependencies for known CVEs",
        "help_uri": "https://github.com/Wolfvin/CodeLens/blob/main/docs/rules/vuln-scan.md",
        "categories": {
            "known_cve": {"id": "codelens/vuln-scan/known-cve", "description": "Known vulnerability in dependency"},
        }
    },
}

# Default rule for unrecognized commands
DEFAULT_RULE = {
    "id_prefix": "codelens/general",
    "name": "CodeLens General Analysis",
    "short_description": "General code analysis finding",
    "help_uri": "https://github.com/Wolfvin/CodeLens",
    "categories": {}
}


def _get_rule_id(command: str, finding: Dict) -> str:
    """Determine the SARIF rule ID for a finding."""
    rule_def = COMMAND_RULES.get(command, DEFAULT_RULE)
    category = finding.get("category", finding.get("type", "general"))
    cat_rules = rule_def.get("categories", {})

    if category in cat_rules:
        return cat_rules[category]["id"]

    # Try to generate a rule ID from the category
    safe_cat = category.lower().replace('_', '-').replace(' ', '-')
    return f"{rule_def['id_prefix']}/{safe_cat}"


def _get_severity(finding: Dict) -> str:
    """Get the severity level from a finding."""
    sev = finding.get("severity", finding.get("risk", "medium"))
    if isinstance(sev, str):
        return sev.lower()
    return "medium"


def _build_rules(command: str, findings: List[Dict]) -> List[Dict]:
    """Build the SARIF rules array from findings."""
    seen_rules = set()
    rules = []
    rule_def = COMMAND_RULES.get(command, DEFAULT_RULE)

    for finding in findings:
        rule_id = _get_rule_id(command, finding)
        if rule_id in seen_rules:
            continue
        seen_rules.add(rule_id)

        # Find the rule definition
        cat = finding.get("category", finding.get("type", "general"))
        cat_rule = rule_def.get("categories", {}).get(cat, {})
        severity = _get_severity(finding)

        rule = {
            "id": rule_id,
            "name": cat_rule.get("description", rule_def.get("name", "CodeLens Finding")),
            "shortDescription": {
                "text": cat_rule.get("description", finding.get("message", finding.get("name", "CodeLens finding")))
            },
            "defaultConfiguration": {
                "level": SEVERITY_TO_LEVEL.get(severity, "warning"),
                "rank": SEVERITY_TO_RANK.get(severity, 50.0),
            },
            "helpUri": rule_def.get("help_uri", ""),
            "properties": {
                "tags": ["codelens", command, cat],
            }
        }

        rules.append(rule)

    # Always include at least one rule
    if not rules:
        rules.append({
            "id": f"{rule_def['id_prefix']}/general",
            "name": rule_def.get("name", "CodeLens Finding"),
            "shortDescription": {"text": rule_def.get("short_description", "CodeLens finding")},
            "defaultConfiguration": {"level": "warning", "rank": 50.0},
        })

    return rules


def _build_results(command: str, findings: List[Dict], workspace: str) -> List[Dict]:
    """Build the SARIF results array from findings."""
    results = []

    for finding in findings:
        rule_id = _get_rule_id(command, finding)
        severity = _get_severity(finding)
        level = SEVERITY_TO_LEVEL.get(severity, "warning")

        # Build location
        file_path = finding.get("file", finding.get("defined_in", ""))
        if file_path and not os.path.isabs(file_path):
            file_path = os.path.relpath(file_path, workspace) if file_path.startswith(workspace) else file_path

        line_num = finding.get("line", finding.get("line_number", 1))
        col_num = finding.get("column", finding.get("col", 1))

        location = {
            "physicalLocation": {
                "artifactLocation": {
                    "uri": file_path.replace('\\', '/') if file_path else "",
                    "uriBaseId": "%SRCROOT%",
                },
                "region": {
                    "startLine": max(1, int(line_num)),
                    "startColumn": max(1, int(col_num)),
                }
            }
        }

        # Build message
        message_text = finding.get("message", finding.get("name", finding.get("match", "")))
        if not message_text:
            message_text = f"{command} finding in {os.path.basename(file_path) if file_path else 'unknown'}"

        result = {
            "ruleId": rule_id,
            "ruleIndex": 0,  # Will be updated when we know the rule index
            "level": level,
            "message": {
                "text": message_text,
            },
            "locations": [location],
            "properties": {},
        }

        # Add optional properties
        if finding.get("confidence"):
            result["properties"]["confidence"] = finding["confidence"]
        if finding.get("taint_path"):
            result["properties"]["taintPath"] = finding["taint_path"]
        if finding.get("cwe"):
            result["properties"]["cwe"] = finding["cwe"]
        if finding.get("sanitized") is not None:
            result["properties"]["sanitized"] = finding["sanitized"]
        if finding.get("category"):
            result["properties"]["category"] = finding["category"]

        # Add related locations for taint analysis
        if finding.get("taint_path") and finding.get("source"):
            source_loc = {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": file_path.replace('\\', '/') if file_path else "",
                        "uriBaseId": "%SRCROOT%",
                    },
                },
                "message": {
                    "text": f"Taint source: {finding['source']}"
                }
            }
            result["relatedLocations"] = [source_loc]

        # Add code flows for data flow / taint
        if finding.get("taint_path"):
            path_parts = finding["taint_path"].split(" → ")
            if len(path_parts) >= 2:
                thread_flow_locations = []
                for i, part in enumerate(path_parts):
                    tfl = {
                        "location": {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": file_path.replace('\\', '/') if file_path else "",
                                    "uriBaseId": "%SRCROOT%",
                                },
                            },
                            "message": {"text": part}
                        },
                        "index": i,
                    }
                    thread_flow_locations.append(tfl)

                result["codeFlows"] = [{
                    "threadFlows": [{
                        "locations": thread_flow_locations,
                    }]
                }]

        results.append(result)

    # Update ruleIndex for each result
    rule_ids = []
    for r in results:
        if r["ruleId"] not in rule_ids:
            rule_ids.append(r["ruleId"])
    for r in results:
        r["ruleIndex"] = rule_ids.index(r["ruleId"])

    return results


def to_sarif(data: Dict, command: str = "", workspace: str = "") -> Dict:
    """Convert CodeLens output to SARIF v2.1.0 format.

    Args:
        data: CodeLens command output dict
        command: Command name (e.g., "secrets", "dead-code")
        workspace: Workspace root path

    Returns:
        SARIF v2.1.0 compliant dict
    """
    # Extract findings from various output formats
    findings = []
    if isinstance(data, dict):
        # Try multiple finding keys
        for key in ("findings", "leaks", "hints", "issues", "violations", "matches", "chains"):
            val = data.get(key)
            if isinstance(val, list):
                findings.extend(val)
            elif isinstance(val, dict):
                # Flatten by_category dicts
                for sub_key, sub_val in val.items():
                    if isinstance(sub_val, list):
                        for item in sub_val:
                            if isinstance(item, dict) and "category" not in item:
                                item["category"] = sub_key
                        findings.extend(sub_val)

    # Build rules and results
    rules = _build_rules(command, findings)
    results = _build_results(command, findings, workspace)

    # Build the SARIF document
    tool = {
        "driver": {
            "name": "CodeLens",
            "version": data.get("version", "7.2.0"),
            "semanticVersion": "7.2.0",
            "informationUri": "https://github.com/Wolfvin/CodeLens",
            "rules": rules,
        }
    }

    run = {
        "tool": tool,
        "results": results,
        "invocations": [{
            "executionSuccessful": True,
            "toolExecutionNotifications": [],
        }],
    }

    # Add workspace info
    if workspace:
        run["originalUriBaseIds"] = {
            "%SRCROOT%": {
                "uri": f"file://{workspace.replace('\\', '/')}/",
            }
        }

    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [run],
    }

    return sarif


def format_sarif(data: Dict, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output as SARIF JSON string."""
    sarif = to_sarif(data, command, workspace)
    return json.dumps(sarif, indent=2, ensure_ascii=False)

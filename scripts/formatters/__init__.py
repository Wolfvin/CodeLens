"""Output formatting for CodeLens CLI."""

import json
from typing import Any, Dict
from formatters.markdown import to_markdown


def _normalize_to_ai(data: Any, command: str = "") -> Dict[str, Any]:
    """Normalize command output to consistent AI-friendly schema.

    Target schema:
    {
        "status": "ok"|"error"|"timeout",
        "command": "...",
        "stats": {...},          # Summary statistics (always present)
        "items": [...],          # Main result items (normalized from findings/leaks/hints/etc)
        "truncated": bool,       # Whether items were truncated
        "recommendations": [...], # Actionable recommendations (if any)
        "metadata": {...}        # Command-specific context (identity, workspace, etc)
    }
    """
    if not isinstance(data, dict):
        return {"status": "ok", "items": [data]}

    status = data.get("status", "ok")
    if status == "error":
        return {
            "status": "error",
            "command": data.get("command", command),
            "error": data.get("error", ""),
            "error_type": data.get("error_type", ""),
            "suggestion": data.get("suggestion", ""),
        }

    result = {
        "status": status,
        "command": command,
    }

    # ─── Extract stats ───
    stats = {}
    if "stats" in data:
        stats = dict(data["stats"]) if isinstance(data["stats"], dict) else data["stats"]
    elif "health_score" in data:
        # smell-like: health_score + total_findings at top level
        stats["health_score"] = data["health_score"]
        stats["total_findings"] = data.get("total_findings", 0)
        if "total_findings" in data:
            pass
        # Merge by_severity / by_category from top level
        for k in ("by_category", "by_severity", "critical", "warning", "info"):
            if k in data:
                stats[k] = data[k]
        if "by_category" in data and isinstance(data["by_category"], dict):
            for cat, items in data["by_category"].items():
                if isinstance(items, list):
                    stats[f"{cat}_count"] = len(items)
    elif "total_cycles" in data:
        # circular
        stats["total_cycles"] = data["total_cycles"]
    elif "total_issues" in data:
        # missing-refs, a11y
        stats["total_issues"] = data["total_issues"]
    elif "identity" in data and "registry_stats" in data:
        # summary
        stats.update(data["registry_stats"])

    result["stats"] = stats

    # ─── Extract items (normalize from various key names) ───
    items = []
    truncated = False

    # Priority order: find the primary result list
    _ITEM_KEYS = [
        "functions", "findings", "leaks", "hints", "issues",
        "matches", "violations", "entrypoints", "routes", "stores",
        "results", "ownership_summary", "chains",
        "by_category", "top_priority", "actionable_items",
    ]

    for key in _ITEM_KEYS:
        val = data.get(key)
        if isinstance(val, list) and len(val) > 0:
            items = val
            break
        elif isinstance(val, dict):
            # Flatten category-keyed dicts (dead-code, smell, etc.)
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list) and len(sub_val) > 0:
                    # Add category to each item
                    for item in sub_val:
                        if isinstance(item, dict) and "category" not in item:
                            item["_category"] = sub_key
                    items.extend(sub_val)
            if items:
                break

    # Handle test-map coverage_map differently
    if not items and "coverage_map" in data:
        cm = data["coverage_map"]
        if isinstance(cm, dict):
            for file_path, file_data in cm.items():
                if isinstance(file_data, dict):
                    for fn_name, fn_data in file_data.items():
                        if isinstance(fn_data, dict):
                            entry = dict(fn_data)
                            entry["file"] = file_path
                            entry["function"] = fn_name
                            items.append(entry)

    result["items"] = items

    # ─── Detect truncation ───
    if data.get("truncated") or data.get("files_truncated") or data.get("_token_truncated"):
        truncated = True
    for key in _ITEM_KEYS:
        if data.get(f"{key}_truncated"):
            truncated = True
            break
    result["truncated"] = truncated

    # ─── Extract recommendations ───
    recs = data.get("recommendations", [])
    if data.get("removal_safety") and "recommended_action" in data:
        recs.append(data["recommended_action"])
    if data.get("actionable_items"):
        recs.extend(data["actionable_items"])
    if data.get("action_plan"):
        recs.extend(data["action_plan"])
    result["recommendations"] = recs[:10]  # Cap recommendations too

    # ─── Metadata: command-specific context ───
    metadata = {}
    _META_KEYS = [
        "workspace", "symbol", "query", "name", "domain", "focus", "detail",
        "direction", "max_depth", "risk", "safety", "found", "action",
        "action_reason", "risk_level", "recommended_action", "fuzzy",
        "partial", "time_budget_used", "health_score",
        "identity", "frameworks_detected", "project_type",
    ]
    for key in _META_KEYS:
        if key in data:
            metadata[key] = data[key]

    # Query-specific: add node info if present
    if "node" in data:
        metadata["node"] = data["node"]
    if "pagination" in data:
        metadata["pagination"] = data["pagination"]

    # ─── Visualization metadata ───
    if "dashboard_path" in data:
        metadata["dashboard_path"] = data["dashboard_path"]
    if "history_snapshot_saved" in data:
        metadata["history_available"] = data.get("history_snapshot_saved", False)
    if "history_snapshot_file" in data:
        metadata["history_snapshot_file"] = data["history_snapshot_file"]

    result["metadata"] = metadata

    # ─── Auto-setup info ───
    if "_auto_setup" in data:
        result["auto_setup"] = data["_auto_setup"]

    return result


def format_output(data: Any, format_type: str = "json", command: str = "") -> str:
    """Format output data as JSON, Markdown, or AI (normalized schema)."""
    if format_type == "ai":
        normalized = _normalize_to_ai(data, command)
        return json.dumps(normalized, indent=2, ensure_ascii=False)
    if format_type == "markdown":
        return to_markdown(data, command)
    # Default: JSON
    return json.dumps(data, indent=2, ensure_ascii=False)

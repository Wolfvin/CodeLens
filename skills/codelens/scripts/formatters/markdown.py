"""Markdown formatting for CodeLens CLI output."""

import os
from typing import Dict, Any


def to_markdown(data: Any, command: str = "") -> str:
    """Convert command output dict to markdown format."""
    if not isinstance(data, dict):
        return str(data)

    lines = []
    status = data.get("status", "")

    # Error output
    if status == "error":
        lines.append(f"## Error")
        lines.append("")
        lines.append(f"**Command:** `{command}`")
        lines.append(f"**Error:** {data.get('error', 'Unknown error')}")
        lines.append(f"**Type:** {data.get('error_type', '')}")
        return "\n".join(lines)

    # Ask command interpretation header (shown when codelens routes ask to a sub-command)
    interp = data.get("query_interpretation")
    if interp:
        lines.append("## Ask")
        lines.append("")
        question = interp.get("question", "")
        interpreted_as = interp.get("interpreted_as", "")
        confidence = interp.get("confidence", "")
        if question:
            lines.append(f"**Question:** {question}")
        if interpreted_as:
            lines.append(f"**Interpreted as:** `{interpreted_as}`")
        if confidence:
            lines.append(f"**Confidence:** {confidence}")
        lines.append("")
        # Remove query_interpretation from data so sub-formatters don't see it
        data = {k: v for k, v in data.items() if k != "query_interpretation"}

    # Command-specific formatting
    if command == "scan":
        _md_scan(data, lines)
    elif command == "query":
        _md_query(data, lines)
    elif command == "context":
        _md_context(data, lines)
    elif command == "outline":
        _md_outline(data, lines)
    elif command == "impact":
        _md_impact(data, lines)
    elif command == "trace":
        _md_trace(data, lines)
    elif command == "smell":
        _md_smell(data, lines)
    elif command == "dead-code":
        _md_dead_code(data, lines)
    elif command == "circular":
        _md_circular(data, lines)
    elif command == "handbook":
        _md_handbook(data, lines)
    elif command == "entrypoints":
        _md_entrypoints(data, lines)
    elif command == "api-map":
        _md_api_map(data, lines)
    elif command == "complexity":
        _md_complexity(data, lines)
    elif command == "secrets":
        _md_secrets(data, lines)
    elif command == "side-effect":
        _md_side_effect(data, lines)
    elif command == "list":
        _md_list(data, lines)
    elif command == "symbols":
        _md_symbols(data, lines)
    elif command == "watch":
        _md_watch(data, lines)
    elif command == "init":
        _md_init(data, lines)
    elif command == "detect":
        _md_detect(data, lines)
    elif command == "search":
        _md_search(data, lines)
    elif command == "missing-refs":
        _md_missing_refs(data, lines)
    elif command == "diff":
        _md_diff(data, lines)
    elif command == "dependents":
        _md_dependents(data, lines)
    elif command == "validate":
        _md_validate(data, lines)
    elif command == "dataflow":
        _md_dataflow(data, lines)
    elif command == "test-map":
        _md_test_map(data, lines)
    elif command == "config-drift":
        _md_config_drift(data, lines)
    elif command == "type-infer":
        _md_type_infer(data, lines)
    elif command == "ownership":
        _md_ownership(data, lines)
    elif command == "debug-leak":
        _md_debug_leak(data, lines)
    elif command == "stack-trace":
        _md_stack_trace(data, lines)
    elif command == "refactor-safe":
        _md_refactor_safe(data, lines)
    elif command == "env-check":
        _md_env_check(data, lines)
    elif command == "state-map":
        _md_state_map(data, lines)
    elif command == "vuln-scan":
        _md_vuln_scan(data, lines)
    elif command == "perf-hint":
        _md_perf_hint(data, lines)
    elif command == "css-deep":
        _md_css_deep(data, lines)
    elif command == "a11y":
        _md_a11y(data, lines)
    elif command == "regex-audit":
        _md_regex_audit(data, lines)
    elif command == "ask":
        _md_ask(data, lines)
    elif command == "binary-scan":
        _md_binary_scan(data, lines)
    else:
        # Generic markdown for any command
        _md_generic(data, lines)

    return "\n".join(lines)


def _md_binary_scan(data: Dict, lines: list) -> None:
    """Markdown formatter for binary-scan command with Tauri RE analysis."""
    lines.append("## Binary Scan")
    lines.append("")

    # Build system
    build_system = data.get("build_system", {})
    detected = build_system.get("detected", [])
    if detected:
        lines.append(f"**Build System:** {', '.join(detected)}")
        lines.append("")

    # Binary stats
    stats = data.get("stats", {})
    if stats.get("total_artifacts", 0) > 0:
        lines.append("### Binary Artifacts")
        lines.append("")
        lines.append(f"| Type | Count | Size |")
        lines.append(f"|------|-------|------|")
        lines.append(f"| Executables | {stats.get('executables', 0)} | - |")
        lines.append(f"| Shared Libraries | {stats.get('shared_libraries', 0)} | - |")
        lines.append(f"| Compiled Objects | {stats.get('compiled_objects', 0)} | - |")
        lines.append(f"| **Total** | **{stats.get('total_artifacts', 0)}** | **{stats.get('total_binary_size_human', '0 B')}** |")
        lines.append("")
    else:
        lines.append("No binary artifacts found in workspace source tree.")
        lines.append("")

    # Tauri analysis
    tauri = data.get("tauri_analysis")
    if tauri:
        lines.append("### Tauri Reverse Engineering Analysis")
        lines.append("")

        summary = tauri.get("summary", {})
        risk = summary.get("risk_level", "unknown")
        risk_emoji = {"critical": "🔴", "high": "🟠", "moderate": "🟡", "low": "🟢"}.get(risk, "⚪")
        lines.append(f"**Risk Level:** {risk_emoji} {risk.upper()}")
        lines.append("")

        # Summary table
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| IPC Commands | {summary.get('ipc_commands_count', 0)} |")
        lines.append(f"| Capabilities | {summary.get('capabilities_count', 0)} |")
        lines.append(f"| Permissions | {summary.get('total_permissions', 0)} |")
        lines.append(f"| Sidecar Binaries | {summary.get('sidecars_count', 0)} |")
        lines.append(f"| Deep Links | {summary.get('deep_links_count', 0)} |")
        lines.append(f"| Security Findings | {summary.get('security_findings', 0)} |")
        lines.append("")

        # Security findings by severity
        by_sev = summary.get("security_findings_by_severity", {})
        if by_sev:
            lines.append("**Security Findings by Severity:**")
            lines.append("")
            for sev in ("critical", "high", "medium", "info"):
                count = by_sev.get(sev, 0)
                if count > 0:
                    lines.append(f"- **{sev.upper()}**: {count}")
            lines.append("")

        # Sidecars
        sidecars = tauri.get("sidecars", [])
        if sidecars:
            lines.append("#### Sidecar Binaries")
            lines.append("")
            for sc in sidecars:
                risk_badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sc.get("risk", "low"), "⚪")
                lines.append(f"- {risk_badge} `{sc.get('name')}` — {sc.get('note', '')}")
            lines.append("")

        # WebView security
        wv = tauri.get("webview_security")
        if wv:
            lines.append("#### WebView Security")
            lines.append("")
            csp = wv.get("csp")
            lines.append(f"- **CSP:** {'Not set (null) ⚠️' if csp is None else f'`{csp}`'}")
            lines.append(f"- **Asset Protocol:** {'Enabled ✅' if wv.get('asset_protocol_enabled') else 'Disabled'}")
            if wv.get('asset_protocol_enabled'):
                scope = wv.get('asset_protocol_scope', {})
                allow = scope.get('allow', [])
                if '**' in str(allow):
                    lines.append(f"  - **Scope:** `**` (wildcard — can read any file) ⚠️")
                else:
                    lines.append(f"  - **Scope:** `{allow}`")
            lines.append("")

        # Updater
        updater = tauri.get("updater")
        if updater:
            lines.append("#### Updater Configuration")
            lines.append("")
            lines.append(f"- **Signed:** {'Yes ✅' if updater.get('pubkey') else 'No ⚠️'}")
            endpoints = updater.get("endpoints", [])
            if endpoints:
                lines.append(f"- **Endpoints:** {len(endpoints)}")
                for ep in endpoints:
                    is_http = 'http://' in ep and 'https://' not in ep

                    lines.append(f"  - {'⚠️ ' if is_http else ''}`{ep}`")
            lines.append("")

        # Deep links
        deep_links = tauri.get("deep_links", [])
        if deep_links:
            lines.append("#### Deep-Link Schemes")
            lines.append("")
            for dl in deep_links:
                lines.append(f"- `{dl.get('scheme')}://`")
            lines.append("")

        # Security audit
        audit = tauri.get("security_audit", [])
        if audit:
            lines.append("#### Security Audit")
            lines.append("")
            # Show critical and high first
            for sev in ("critical", "high"):
                findings = [f for f in audit if f.get("severity") == sev]
                if findings:
                    lines.append(f"**{sev.upper()} Findings:**")
                    lines.append("")
                    for f in findings:
                        lines.append(f"- **{f.get('category')}** — {f.get('message')}")
                        if f.get('file'):
                            lines.append(f"  - File: `{f.get('file')}`")
                    lines.append("")
            # Medium findings summary
            medium = [f for f in audit if f.get("severity") == "medium"]
            if medium:
                lines.append(f"**MEDIUM Findings:** {len(medium)}")
                lines.append("")
                for f in medium[:5]:
                    lines.append(f"- **{f.get('category')}** — {f.get('message')[:120]}")
                if len(medium) > 5:
                    lines.append(f"- ... and {len(medium) - 5} more")
                lines.append("")

        # IPC commands
        ipc_cmds = tauri.get("ipc_commands", [])
        if ipc_cmds:
            lines.append("#### IPC Commands")
            lines.append("")
            lines.append(f"Found {len(ipc_cmds)} Tauri IPC command(s):")
            lines.append("")
            for cmd in ipc_cmds[:20]:
                async_badge = " (async)" if cmd.get("is_async") else ""
                callers = cmd.get("called_from", [])
                caller_info = f" ← called from {len(callers)} frontend file(s)" if callers else ""
                lines.append(f"- `{cmd.get('name')}`{async_badge} — `{cmd.get('file')}:{cmd.get('line')}`{caller_info}")
            if len(ipc_cmds) > 20:
                lines.append(f"- ... and {len(ipc_cmds) - 20} more")
            lines.append("")

    # Recommendations
    recs = data.get("recommendations", [])
    if recs:
        lines.append("### Recommendations")
        lines.append("")
        for rec in recs:
            lines.append(f"- {rec}")
        lines.append("")


def _md_generic(data: Dict, lines: list) -> None:
    """Generic markdown output for any command."""
    lines.append(f"## Result")
    lines.append("")
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"- **{key}:** {value}")
        elif isinstance(value, list) and len(value) < 20:
            lines.append(f"- **{key}:** {len(value)} items")
            for item in value[:10]:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("file") or item.get("path") or str(item)[:50]
                    lines.append(f"  - {name}")
                else:
                    lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"- **{key}:** {len(value)} entries")
        elif isinstance(value, list):
            lines.append(f"- **{key}:** {len(value)} items")
    lines.append("")


def _md_scan(data: Dict, lines: list) -> None:
    """Markdown for scan command."""
    lines.append("## Scan Result")
    lines.append("")
    fs = data.get("files_scanned", {})
    lines.append(f"- **Workspace:** `{data.get('workspace', '')}`")
    for ftype, count in fs.items():
        if count > 0:
            lines.append(f"- **{ftype}:** {count} files")
    fe = data.get("frontend", {})
    be = data.get("backend", {})
    lines.append(f"- **Frontend:** {fe.get('classes', 0)} classes, {fe.get('ids', 0)} IDs")
    lines.append(f"- **Backend:** {be.get('nodes', 0)} nodes, {be.get('edges', 0)} edges")
    fws = data.get("frameworks", [])
    if fws:
        lines.append(f"- **Frameworks:** {', '.join(fws)}")
    outline_gen = data.get("outline_generated")
    if outline_gen is not None:
        lines.append(f"- **Outline generated:** {'Yes' if outline_gen else 'No'}")
    lines.append("")


def _md_query(data: Dict, lines: list) -> None:
    """Markdown for query command."""
    name = data.get("name", "") or data.get("node", {}).get("fn", "")
    found = data.get("found", False)
    status = data.get("status", "") or data.get("node", {}).get("status", "")
    action = data.get("action", "")
    action_reason = data.get("action_reason", "")

    icon = "Found" if found else "Not found"
    lines.append(f"## Query: `{name}`")
    lines.append("")
    lines.append(f"**Status:** {icon}" + (f" ({status})" if status and found else ""))
    if action:
        lines.append(f"**Action:** {action}")
    if action_reason:
        lines.append(f"**Reason:** {action_reason}")
    lines.append("")

    # Callers
    callers = data.get("callers", [])
    if callers:
        lines.append("### Callers")
        for c in callers[:20]:
            cfrom = c.get("from", "")
            cfn = c.get("fn", "")
            label = f"`{cfn}`" if cfn else ""
            loc = f"`{cfrom}`" if cfrom else ""
            if label and loc:
                lines.append(f"- {label} — {loc}")
            elif loc:
                lines.append(f"- {loc}")
            elif label:
                lines.append(f"- {label}")
        lines.append("")

    # Callees
    callees = data.get("callees", [])
    if callees:
        lines.append("### Callees")
        for c in callees[:20]:
            cto = c.get("to", "") or c.get("to_fn", "")
            cfn = c.get("fn", "")
            resolved = c.get("resolved", True)
            label = f"`{cfn}`" if cfn else f"`{cto}`"
            status_str = "" if resolved else " (unresolved)"
            loc = f" → `{cto}`" if cto and cfn else ""
            lines.append(f"- {label}{loc}{status_str}")
        lines.append("")

    # Generic references fallback (for non-backend domains)
    refs = data.get("references", [])
    if refs and not callers and not callees:
        lines.append("### References")
        for ref in refs[:20]:
            rtype = ref.get("type", "")
            rname = ref.get("name", name)
            file_path = ref.get("file", "")
            line = ref.get("line", "")
            status_str = ref.get("status", "")
            lines.append(f"- `{rname}` ({rtype}) — `{file_path}:{line}` [{status_str}]")
        lines.append("")


def _md_context(data: Dict, lines: list) -> None:
    """Markdown for context command."""
    symbol = data.get("symbol", "")
    found = data.get("found", False)
    ctx = data.get("context", {})

    # Handle file path context (type: "file" or "files")
    if found and ctx and ctx.get("type") in ("file", "files"):
        if ctx.get("type") == "file":
            lines.append(f"## Context: `{ctx.get('file', symbol)}`")
            lines.append("")
            syms = ctx.get("symbols", [])
            lines.append(f"**Symbols:** {len(syms)}")
            lines.append("")
            for s in syms:
                lines.append(f"- `{s.get('fn', '?')}` (line {s.get('line', '?')}) — status: {s.get('status', 'active')}, refs: {s.get('ref_count', 0)}")
            lines.append("")
        elif ctx.get("type") == "files":
            files = ctx.get("files", [])
            lines.append(f"## Context: `{symbol}` (matched {len(files)} files)")
            lines.append("")
            for f_entry in files:
                lines.append(f"### `{f_entry.get('file', '?')}`")
                for s in f_entry.get("symbols", []):
                    lines.append(f"- `{s.get('fn', '?')}` (line {s.get('line', '?')}) — status: {s.get('status', 'active')}, refs: {s.get('ref_count', 0)}")
                lines.append("")
        return

    lines.append(f"## Context: `{symbol}`")
    lines.append("")

    if not found or not ctx:
        lines.append("Symbol not found.")
        lines.append("")
        return

    defn = ctx.get("definition") or {}
    lines.append(f"**Type:** {defn.get('type', 'unknown')} | **Status:** {defn.get('status', '')} | **Refs:** {defn.get('ref_count', 0)}")
    lines.append("")

    # Code snippet
    snippet = ctx.get("code_snippet")
    if snippet:
        lines.append("### Definition")
        ext = os.path.splitext(snippet.get("file", ""))[1].lstrip(".")
        lang_map = {"py": "python", "js": "javascript", "ts": "typescript", "tsx": "tsx", "rs": "rust"}
        lang = lang_map.get(ext, ext)
        lines.append(f"```{lang}")
        for line_info in snippet.get("lines", []):
            prefix = ">>>" if line_info.get("is_target") else "   "
            lines.append(f"{prefix} {line_info.get('line', ''):4d} | {line_info.get('content', '')}")
        lines.append("```")
        lines.append("")

    # Callers
    callers = ctx.get("callers", [])
    if callers:
        lines.append("### Callers")
        for c in callers[:10]:
            lines.append(f"- `{c.get('file', '')}:{c.get('line', '')}` — {c.get('source', c.get('fn', ''))}")
        lines.append("")

    # Callees
    callees = ctx.get("callees", [])
    if callees:
        lines.append("### Callees")
        for c in callees[:10]:
            resolved = "resolved" if c.get("resolved") else "unresolved"
            lines.append(f"- {c.get('fn', '')} → `{c.get('file', '')}:{c.get('line', '')}` [{resolved}]")
        lines.append("")

    # Quality (if enriched)
    quality = ctx.get("quality")
    if quality:
        lines.append("### Quality")
        lines.append(f"- **Complexity:** {quality.get('complexity', 'N/A')}")
        lines.append(f"- **Side effects:** {quality.get('side_effects', 'N/A')}")
        lines.append(f"- **Safety:** {quality.get('safety', 'N/A')}")
        smells = quality.get("smells", [])
        if smells:
            lines.append(f"- **Smells:** {', '.join(smells)}")
        lines.append("")


def _md_outline(data: Dict, lines: list) -> None:
    """Markdown for outline command."""
    if "outlines" in data:
        # Workspace outline
        lines.append(f"## Workspace Outline ({data.get('files_outlined', 0)} files)")
        lines.append("")
        for outline in data.get("outlines", []):
            file = outline.get("file", "")
            lang = outline.get("language", "")
            lines.append(f"### `{file}` ({lang})")
            ol = outline.get("outline", {})
            for key, items in ol.items():
                if isinstance(items, list) and items:
                    lines.append(f"- **{key}:** {len(items)}")
            lines.append("")
    else:
        # Single file outline
        file = data.get("file", "")
        lines.append(f"## Outline: `{file}`")
        lines.append("")
        ol = data.get("outline", {})
        for key, items in ol.items():
            if isinstance(items, list) and items:
                lines.append(f"- **{key}:** {len(items)}")


def _md_impact(data: Dict, lines: list) -> None:
    """Markdown for impact command."""
    lines.append(f"## Impact Analysis: `{data.get('symbol', '')}`")
    lines.append("")
    risk = data.get("risk_level", data.get("risk", ""))
    action_plan = data.get("recommended_action", data.get("action", ""))
    if risk:
        lines.append(f"**Risk Level:** {risk}")
    if action_plan:
        lines.append(f"**Recommended Action:** {action_plan}")
    lines.append("")
    affected = data.get("affected", data.get("affected_files", []))
    if affected:
        lines.append("### Affected")
        if isinstance(affected, dict):
            for group_name, items in affected.items():
                if isinstance(items, list) and items:
                    if group_name:
                        lines.append(f"**{group_name.title()}:**")
                    for a in items[:20]:
                        if isinstance(a, dict):
                            lines.append(f"- `{a.get('file', '')}:{a.get('line', '')}` — {a.get('type', a.get('fn', a.get('name', '')))}")
                        else:
                            lines.append(f"- {a}")
        elif isinstance(affected, list):
            for a in affected[:20]:
                if isinstance(a, dict):
                    lines.append(f"- `{a.get('file', '')}:{a.get('line', '')}` — {a.get('type', a.get('fn', ''))}")
                else:
                    lines.append(f"- {a}")
        lines.append("")


def _format_trace_chain(chain) -> str:
    """Format a single trace chain entry as a readable bullet point.

    The ``path`` field from ``_bfs_trace`` is a string like
    ``"file:line:fn → file:line:fn"``, NOT a list.  Older code treated it
    as an iterable and ended up splitting the string character-by-character
    (``p → a → c → k → …``).  This helper handles both string and list
    paths correctly.
    """
    if isinstance(chain, dict):
        path = chain.get("path", "")
        if isinstance(path, str) and path:
            # Path is already a formatted string with → separators
            fn = chain.get("fn", "")
            file = chain.get("file", "")
            line = chain.get("line", "")
            depth = chain.get("depth", 0)
            cyclic = chain.get("cyclic", False)
            resolved = chain.get("resolved", True)

            # Build a readable entry: show function@file:line with depth indent
            parts = []
            if fn:
                label = fn
            else:
                label = path.split(" → ")[-1] if " → " in path else path
            if file:
                label = f"`{label}` ({file}"
                if line:
                    label += f":{line}"
                label += ")"
            else:
                label = f"`{label}`"
            if cyclic:
                label += " ↻ cyclic"
            if not resolved:
                label += " ⚠ unresolved"

            indent = "  " * min(depth, 5)
            return f"{indent}- {label}"
        elif isinstance(path, list) and path:
            return f"- {' → '.join(str(p) for p in path)}"
        else:
            # Fallback: use fn/file/depth
            fn = chain.get("fn", "")
            file = chain.get("file", "")
            depth = chain.get("depth", 0)
            cyclic = chain.get("cyclic", False)
            indent = "  " * min(depth, 5)
            entry = f"{indent}- `{fn}`" if fn else f"{indent}- (unknown)"
            if file:
                entry += f" ({file}"
                line = chain.get("line", "")
                if line:
                    entry += f":{line}"
                entry += ")"
            if cyclic:
                entry += " ↻ cyclic"
            return entry
    elif isinstance(chain, list):
        return f"- {' → '.join(str(p) for p in chain)}"
    else:
        return f"- {chain}"


def _md_trace(data: Dict, lines: list) -> None:
    """Markdown for trace command."""
    lines.append(f"## Trace: `{data.get('symbol', data.get('name', ''))}`")
    lines.append("")
    direction = data.get("direction", "")
    if direction:
        lines.append(f"**Direction:** {direction}")
    lines.append("")
    chains = data.get("chains", data.get("trace", []))
    if chains:
        if isinstance(chains, dict):
            # chains is a dict with direction keys (up/down)
            for dir_key, dir_chains in chains.items():
                if isinstance(dir_chains, list) and dir_chains:
                    lines.append(f"### {dir_key.title()}")
                    for chain in dir_chains[:15]:
                        lines.append(_format_trace_chain(chain))
                    lines.append("")
        elif isinstance(chains, list):
            for chain in chains[:15]:
                lines.append(_format_trace_chain(chain))
            lines.append("")


def _md_smell(data: Dict, lines: list) -> None:
    """Markdown for smell command."""
    stats = data.get("stats", {})
    lines.append("## Code Smells")
    lines.append("")
    lines.append(f"**Health Score:** {stats.get('health_score', 0)}/100")
    lines.append(f"- Critical: {stats.get('critical', 0)} | Warning: {stats.get('warning', 0)} | Info: {stats.get('info', 0)}")
    lines.append("")
    top = data.get("top_priority", [])
    if top:
        lines.append("### Top Priority")
        for smell in top[:10]:
            cat = smell.get("category", "")
            file = smell.get("file", "")
            line = smell.get("line", "")
            msg = smell.get("message", "")
            sev = smell.get("severity", "")
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: {msg}")
        lines.append("")


def _md_dead_code(data: Dict, lines: list) -> None:
    """Markdown for dead-code command."""
    stats = data.get("stats", {})
    lines.append("## Dead Code Analysis")
    lines.append("")
    lines.append(f"- Total dead: {stats.get('total_dead_code', 0)}")
    by_cat = stats.get("by_category", {})
    parts = []
    if by_cat.get("unreachable", 0):
        parts.append(f"Unreachable: {by_cat['unreachable']}")
    if by_cat.get("unused_exports", 0):
        parts.append(f"Unused exports: {by_cat['unused_exports']}")
    if by_cat.get("unused_vars", 0):
        parts.append(f"Unused vars: {by_cat['unused_vars']}")
    if by_cat.get("zombie_css", 0):
        parts.append(f"Zombie CSS: {by_cat['zombie_css']}")
    if by_cat.get("registry_dead", 0):
        parts.append(f"Registry dead: {by_cat['registry_dead']}")
    if parts:
        lines.append("- " + " | ".join(parts))
    removal_safety = data.get("removal_safety", "")
    if removal_safety:
        lines.append(f"- **Removal safety:** {removal_safety}")
    lines.append("")

    # Show items from each category
    results = data.get("results", {})
    shown = 0
    max_show = 20

    for cat_name, items in results.items():
        if not items or shown >= max_show:
            continue
        lines.append(f"### {cat_name.replace('_', ' ').title()}")
        lines.append("")
        for item in items[:10]:
            file = item.get("file", "")
            line = item.get("line", "")
            dtype = item.get("type", item.get("category", ""))
            name = item.get("name", item.get("fn", ""))
            msg = item.get("message", "")
            if msg:
                lines.append(f"- `{file}:{line}` — {name}: {msg}")
            else:
                lines.append(f"- `{file}:{line}` — {dtype}: {name}")
            shown += 1
        lines.append("")


def _md_circular(data: Dict, lines: list) -> None:
    """Markdown for circular command."""
    cycles = data.get("cycles", {})
    total = data.get("total_cycles", 0)
    lines.append("## Circular Dependencies")
    lines.append("")
    lines.append(f"**Found:** {total} circular chain(s)")
    lines.append("")

    # Severity breakdown summary
    sev = data.get("severity_breakdown", {})
    if sev:
        genuine = sev.get("genuine_warning", 0)
        false_pos = sev.get("likely_false_positive_info", 0)
        critical = sev.get("critical", 0)
        parts = []
        if critical:
            parts.append(f"{critical} critical cycle(s)")
        if genuine:
            parts.append(f"{genuine} genuine cycle(s) (warning)")
        if false_pos:
            parts.append(f"{false_pos} likely false positive(s) from trait impls (info)")
        if parts:
            lines.append("**Summary:** " + " | ".join(parts))
            lines.append("")

    # Summary per category
    summary = data.get("summary", {})
    if summary:
        parts = []
        fc = summary.get("function_call_cycles", 0)
        if fc:
            parts.append(f"{fc} function call(s)")
        ic = summary.get("import_chain_cycles", 0)
        if ic:
            parts.append(f"{ic} import chain(s)")
        cc = summary.get("css_import_cycles", 0)
        if cc:
            parts.append(f"{cc} CSS import(s)")
        if parts:
            lines.append("**Breakdown:** " + " | ".join(parts))
            lines.append("")

    # Show cycles from each category (up to 10 total)
    shown = 0
    max_show = 10
    for category in ("function_calls", "import_chains", "css_imports"):
        cat_cycles = cycles.get(category, [])
        if not cat_cycles:
            continue
        lines.append(f"### {category.replace('_', ' ').title()}")
        lines.append("")
        for cycle in cat_cycles:
            if shown >= max_show:
                break
            cycle_str = cycle.get("cycle", "")
            severity = cycle.get("severity", "")
            msg = cycle.get("message", cycle_str)
            if severity:
                lines.append(f"- [{severity}] {msg}")
            else:
                lines.append(f"- {msg}")
            shown += 1
        if shown >= max_show:
            break
        lines.append("")

    if total > max_show:
        lines.append(f"_... and {total - max_show} more cycle(s)_")
        lines.append("")


def _md_handbook(data: Dict, lines: list) -> None:
    """Markdown for handbook command."""
    identity = data.get("identity", {})
    meta = data.get("meta", {})
    health = data.get("health", {})
    structure = data.get("structure", {})
    conventions = data.get("conventions", {})
    risks = data.get("risks", [])
    qr = data.get("quick_reference", {})

    lines.append(f"# Project Handbook: {identity.get('name', 'unknown')}")
    lines.append("")

    desc = identity.get("description", "")
    if desc:
        lines.append(f"**{desc}**")
        lines.append("")

    fws = data.get("frameworks", [])
    lines.append(f"Type: **{identity.get('type', 'unknown')}** | Version: {identity.get('version', '0.0.0')} | Frameworks: {', '.join(fws) if fws else 'none'}")
    lines.append("")

    lines.append(f"## Health: {health.get('score', 0)}/100")
    lines.append(f"- Smells: {health.get('smells_count', 0)} | Critical: {health.get('critical', 0)} | Warning: {health.get('warning', 0)}")
    lines.append("")

    # Structure
    dir_map = structure.get("directory_map", {})
    if dir_map:
        lines.append("## Structure")
        for dir_path, desc in dir_map.items():
            lines.append(f"- `{dir_path}` — {desc}")
        lines.append("")

    # Quick Reference
    lines.append("## Quick Reference")
    lines.append(f"- Files: {qr.get('total_files', 0)} | Functions: {qr.get('total_functions', 0)} | Classes: {qr.get('total_classes', 0)} | Exports: {qr.get('total_exports', 0)}")
    lines.append("")

    # Risks
    if risks:
        lines.append("## Risks")
        for r in risks:
            rtype = r.get("type", "")
            count = r.get("count", 0)
            desc = r.get("description", "")
            if count:
                lines.append(f"- {rtype.replace('_', ' ')}: {count}")
            elif desc:
                lines.append(f"- {desc}")
        lines.append("")

    # Conventions
    naming = conventions.get("naming", {})
    if naming:
        lines.append("## Conventions")
        for key, val in naming.items():
            lines.append(f"- {key}: {val}")
        lines.append("")

    lines.append(f"Generated: {meta.get('generated_at', 'unknown')}")


def _md_entrypoints(data: Dict, lines: list) -> None:
    """Markdown for entrypoints command."""
    lines.append("## Entrypoints")
    lines.append("")
    eps = data.get("entrypoints", [])
    for ep in eps[:20]:
        etype = ep.get("type", "")
        file = ep.get("file", "")
        line = ep.get("line", "")
        label = ep.get("label", "")
        extra = ""
        if etype == "http_handler":
            extra = f" `{ep.get('method', '')} {ep.get('path', '')}`"
        # Use angle brackets to avoid markdown link reference interpretation.
        # [main] gets consumed as a markdown link ref, showing "ain]" instead.
        lines.append(f"- <{etype}> `{file}:{line}` — {label}{extra}")
    lines.append("")


def _md_api_map(data: Dict, lines: list) -> None:
    """Markdown for api-map command."""
    lines.append("## API Routes")
    lines.append("")
    routes = data.get("routes", [])
    for r in routes[:30]:
        method = r.get("method", "GET")
        path = r.get("path", "/")
        handler = r.get("handler_name", "")
        file = r.get("file", "")
        auth = " [auth]" if r.get("auth_protected") else ""
        lines.append(f"- **{method}** `{path}` → {handler} (`{file}`){auth}")
    lines.append("")


def _md_complexity(data: Dict, lines: list) -> None:
    """Markdown for complexity command."""
    stats = data.get("stats", {})
    lines.append("## Complexity Analysis")
    lines.append("")
    lines.append(f"- Total functions: {stats.get('total_functions', 0)}")
    lines.append(f"- Avg cyclomatic: {stats.get('avg_cyclomatic', 0):.1f} | Avg cognitive: {stats.get('avg_cognitive', 0):.1f}")
    by_level = stats.get("by_complexity_level", {})
    if by_level:
        parts = [f"{k}: {v}" for k, v in by_level.items() if v > 0]
        lines.append(f"- Levels: {', '.join(parts)}")
    lines.append("")
    hotspots = data.get("hotspots", [])
    if hotspots:
        lines.append("### Hotspots")
        for hs in hotspots[:10]:
            lines.append(f"- `{hs.get('file', '')}:{hs.get('line', '')}` — {hs.get('name', '')} (CC={hs.get('cyclomatic', 0)})")
        lines.append("")


def _md_secrets(data: Dict, lines: list) -> None:
    """Markdown for secrets command."""
    stats = data.get("stats", {})
    lines.append("## Secrets Scan")
    lines.append("")
    lines.append(f"- Total secrets: {stats.get('total_secrets', 0)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Findings")
        for finding in findings[:15]:
            sev = finding.get("severity", "")
            lines.append(f"- [{sev.upper()}] `{finding.get('file', '')}:{finding.get('line', '')}` — {finding.get('type', '')}")
        lines.append("")


def _md_side_effect(data: Dict, lines: list) -> None:
    """Markdown for side-effect command."""
    stats = data.get("stats", {})
    lines.append("## Side Effect Analysis")
    lines.append("")
    lines.append(f"- Pure: {stats.get('pure', 0)} | Impure: {stats.get('impure', 0)} | Purity ratio: {stats.get('purity_ratio', 0):.0%}")
    effects = stats.get("effect_summary", {})
    if effects:
        parts = [f"{k}: {v}" for k, v in effects.items() if v > 0]
        lines.append(f"- Effects: {', '.join(parts)}")
    lines.append("")
    functions = data.get("functions", [])
    if functions:
        lines.append("### Impure Functions")
        for fn in functions[:15]:
            if fn.get("classification") == "impure":
                effects_list = ", ".join(e.get("type", "") for e in fn.get("side_effects", []))
                lines.append(f"- `{fn.get('file', '')}:{fn.get('line', '')}` — {fn.get('name', '')} ({effects_list})")
        lines.append("")


# ─── 26 New Formatters ──────────────────────────────────────────


def _md_list(data: Dict, lines: list) -> None:
    """Markdown for list command."""
    domain = data.get("domain", "all")
    filter_type = data.get("filter", "all")
    count = data.get("count", 0)
    lines.append("## Symbol List")
    lines.append("")
    lines.append(f"**Domain:** {domain} | **Filter:** {filter_type} | **Total:** {count}")
    lines.append("")
    entries = data.get("results", [])
    if entries:
        for e in entries[:30]:
            name = e.get("name", "")
            etype = e.get("type", "")
            status = e.get("status", "")
            defined = e.get("defined_in", "")
            ref_count = e.get("ref_count", "")
            loc = f" `{defined}`" if defined else ""
            refs = f" refs:{ref_count}" if ref_count != "" else ""
            lines.append(f"- `{name}` ({etype}) [{status}]{loc}{refs}")
        if len(entries) > 30:
            lines.append(f"- ... and {len(entries) - 30} more")
    lines.append("")


def _md_symbols(data: Dict, lines: list) -> None:
    """Markdown for symbols command."""
    query = data.get("query", "")
    domain = data.get("domain", "all")
    count = data.get("count", 0)
    fuzzy = data.get("fuzzy", False)
    lines.append(f"## Symbol Search: `{query}`")
    lines.append("")
    lines.append(f"**Domain:** {domain} | **Fuzzy:** {fuzzy} | **Results:** {count}")
    lines.append("")
    results = data.get("results", [])
    if results:
        for r in results[:20]:
            name = r.get("name", r.get("fn", ""))
            rtype = r.get("type", "")
            file = r.get("file", "")
            line = r.get("line", "")
            status = r.get("status", "")
            loc = r.get("location", f"{file}:{line}" if file or line else "")
            lines.append(f"- `{name}` ({rtype}) — `{loc}` [{status}]")
        if len(results) > 20:
            lines.append(f"- ... and {len(results) - 20} more")
    lines.append("")


def _md_watch(data: Dict, lines: list) -> None:
    """Markdown for watch command."""
    status = data.get("status", "stopped")
    lines.append("## Watch")
    lines.append("")
    lines.append(f"**Status:** {status}")
    lines.append("")
    lines.append("Watch mode runs interactively. Use the CLI directly for real-time output.")
    lines.append("")


def _md_init(data: Dict, lines: list) -> None:
    """Markdown for init command."""
    workspace = data.get("workspace", "")
    codelens_dir = data.get("codelens_dir", "")
    config = data.get("config", {})
    lines.append("## CodeLens Init")
    lines.append("")
    lines.append(f"**Workspace:** `{workspace}`")
    lines.append(f"**Config dir:** `{codelens_dir}`")
    lines.append("")
    if config:
        lines.append("### Auto-detected Config")
        fws = config.get("frameworks", [])
        if fws:
            lines.append(f"- **Frameworks:** {', '.join(fws)}")
        if config.get("css_preprocessor"):
            lines.append(f"- **CSS preprocessor:** {config['css_preprocessor']}")
        if config.get("module_system"):
            lines.append(f"- **Module system:** {config['module_system']}")
        modes = []
        if config.get("jsx_mode"):
            modes.append("JSX")
        if config.get("vue_mode"):
            modes.append("Vue")
        if config.get("svelte_mode"):
            modes.append("Svelte")
        if config.get("tailwind_mode"):
            modes.append("Tailwind")
        if modes:
            lines.append(f"- **Modes:** {', '.join(modes)}")
        fe_paths = config.get("frontend_paths", [])
        be_paths = config.get("backend_paths", [])
        if fe_paths:
            lines.append(f"- **Frontend paths:** {', '.join(fe_paths[:5])}")
        if be_paths:
            lines.append(f"- **Backend paths:** {', '.join(be_paths[:5])}")
    lines.append("")


def _md_detect(data: Dict, lines: list) -> None:
    """Markdown for detect command."""
    frameworks = data.get("frameworks", [])
    lines.append("## Framework Detection")
    lines.append("")
    if frameworks:
        lines.append(f"**Detected:** {', '.join(frameworks)}")
    else:
        lines.append("**No frameworks detected**")
    lines.append("")
    flags = []
    if data.get("has_react"):
        flags.append("React")
    if data.get("has_nextjs"):
        flags.append("Next.js")
    if data.get("has_vue"):
        flags.append("Vue")
    if data.get("has_svelte"):
        flags.append("Svelte")
    if data.get("has_tailwind"):
        flags.append("Tailwind")
    if data.get("has_angular"):
        flags.append("Angular")
    if data.get("has_fastapi"):
        flags.append("FastAPI")
    if data.get("has_flask"):
        flags.append("Flask")
    if data.get("has_django"):
        flags.append("Django")
    if data.get("has_tauri"):
        flags.append("Tauri")
    if data.get("has_rust_backend"):
        flags.append("Rust")
    if flags:
        lines.append(f"- **Flags:** {', '.join(flags)}")
    if data.get("css_preprocessor"):
        lines.append(f"- **CSS preprocessor:** {data['css_preprocessor']}")
    if data.get("module_system"):
        lines.append(f"- **Module system:** {data['module_system']}")
    if data.get("is_monorepo"):
        lines.append("- **Monorepo:** Yes")
    if data.get("lockfile"):
        lines.append(f"- **Lockfile:** {data['lockfile']}")
    lines.append("")


def _md_search(data: Dict, lines: list) -> None:
    """Markdown for search command."""
    pattern = data.get("pattern", "")
    stats = data.get("stats", {})
    lines.append(f"## Search: `{pattern}`")
    lines.append("")
    lines.append(f"**Files searched:** {stats.get('files_searched', 0)} | **Matched:** {stats.get('files_matched', 0)} | **Hits:** {stats.get('total_matches', 0)}")
    if stats.get("truncated"):
        lines.append(" (truncated)")
    lines.append("")
    matches = data.get("matches", [])
    if matches:
        for m in matches[:30]:
            file = m.get("file", "")
            line = m.get("line", "")
            text = m.get("text", m.get("match", "")).strip()[:80]
            lines.append(f"- `{file}:{line}` — {text}")
        if len(matches) > 30:
            lines.append(f"- ... and {len(matches) - 30} more")
    errors = data.get("errors", [])
    if errors:
        lines.append(f"**Errors:** {len(errors)} files could not be read")
    lines.append("")


def _md_missing_refs(data: Dict, lines: list) -> None:
    """Markdown for missing-refs command."""
    total = data.get("total_issues", 0)
    summary = data.get("summary", {})
    lines.append("## Missing References")
    lines.append("")
    lines.append(f"**Total issues:** {total}")
    lines.append(f"- CSS no HTML: {summary.get('css_no_html', 0)} | HTML no CSS: {summary.get('html_no_css', 0)}")
    lines.append(f"- CSS ID no HTML: {summary.get('css_id_no_html', 0)} | JS ID no HTML: {summary.get('js_id_no_html', 0)}")
    lines.append(f"- Possible typos: {summary.get('possible_typos', 0)}")
    lines.append("")
    issues = data.get("issues", {})
    # Show each issue category
    for cat in ["css_no_html", "html_no_css", "css_id_no_html", "js_id_no_html", "possible_typos"]:
        items = issues.get(cat, [])
        if items:
            lines.append(f"### {cat.replace('_', ' ').title()}")
            for item in items[:10]:
                name = item.get("name", "")
                file = item.get("file", item.get("css_file", item.get("html_file", "")))
                line = item.get("line", "")
                lines.append(f"- `{name}` in `{file}:{line}`")
            if len(items) > 10:
                lines.append(f"- ... and {len(items) - 10} more")
            lines.append("")


def _md_diff(data: Dict, lines: list) -> None:
    """Markdown for diff command."""
    # Check if it's a snapshot list
    snapshots = data.get("snapshots", [])
    if snapshots:
        lines.append("## Snapshots")
        lines.append("")
        lines.append(f"**Total:** {len(snapshots)}")
        lines.append("")
        for s in snapshots[:20]:
            sid = s.get("id", "")
            created = s.get("created_at", "")
            fname = s.get("file", "")
            lines.append(f"- `{sid}` — {created} ({fname})")
        lines.append("")
        return

    # Regular diff
    summary = data.get("summary", {})
    workspace = data.get("workspace", "")
    snap1 = data.get("snapshot_1", data.get("last_snapshot", ""))
    snap2 = data.get("snapshot_2", "")
    lines.append("## Registry Diff")
    lines.append("")
    if snap1:
        lines.append(f"**Comparing:** `{snap1}` → `{snap2 or 'current'}`")
    lines.append("")

    fe = data.get("frontend", {})
    be = data.get("backend", {})

    if fe:
        added = fe.get("added_count", 0)
        removed = fe.get("removed_count", 0)
        changed = fe.get("changed_count", 0)
        lines.append(f"### Frontend — +{added} / -{removed} / ~{changed}")
        for cls in fe.get("added_classes", [])[:5]:
            lines.append(f"- + `{cls.get('name', '')}` [{cls.get('status', '')}]")
        for cls in fe.get("removed_classes", [])[:5]:
            lines.append(f"- - `{cls.get('name', '')}`")
        for cls in fe.get("changed_classes", [])[:5]:
            lines.append(f"- ~ `{cls.get('name', '')}`")
        for id_entry in fe.get("added_ids", [])[:5]:
            lines.append(f"- + ID `{id_entry.get('name', '')}`")
        for id_entry in fe.get("removed_ids", [])[:5]:
            lines.append(f"- - ID `{id_entry.get('name', '')}`")
        if fe.get("new_collisions"):
            lines.append(f"- **New collisions:** {len(fe['new_collisions'])}")
        if fe.get("new_dead"):
            lines.append(f"- **New dead:** {len(fe['new_dead'])}")
        lines.append("")

    if be:
        added = be.get("added_count", 0)
        removed = be.get("removed_count", 0)
        changed = be.get("changed_count", 0)
        lines.append(f"### Backend — +{added} / -{removed} / ~{changed}")
        for node in be.get("added_nodes", [])[:5]:
            lines.append(f"- + `{node.get('fn', '')}` ({node.get('file', '')})")
        for node in be.get("removed_nodes", [])[:5]:
            lines.append(f"- - `{node.get('fn', '')}`")
        for node in be.get("changed_nodes", [])[:5]:
            lines.append(f"- ~ `{node.get('fn', '')}`")
        if be.get("new_dead"):
            lines.append(f"- **New dead:** {len(be['new_dead'])}")
        lines.append("")


def _md_dependents(data: Dict, lines: list) -> None:
    """Markdown for dependents command."""
    # Check if it's a dependency graph
    graph = data.get("graph", {})
    if graph:
        stats = data.get("stats", {})
        lines.append("## Dependency Graph")
        lines.append("")
        lines.append(f"**Files:** {stats.get('total_files', 0)} | **Edges:** {stats.get('total_import_edges', 0)} | **Leaves:** {stats.get('leaf_files', 0)} | **Roots:** {stats.get('root_files', 0)}")
        lines.append("")
        most_depended = data.get("most_depended_on", [])
        if most_depended:
            lines.append("### Most Depended On")
            for item in most_depended[:10]:
                lines.append(f"- `{item.get('file', '')}` — {item.get('dependents', item.get('count', 0))} dependents")
            lines.append("")
        leaves = data.get("leaf_files", [])
        if leaves:
            lines.append("### Leaf Files")
            for lf in leaves[:10]:
                lines.append(f"- `{lf}`")
            lines.append("")
        return

    # Single file dependents or dependencies
    file = data.get("file", "")
    stats = data.get("stats", {})
    direct = data.get("direct_dependents", data.get("direct_dependencies", []))
    transitive = data.get("transitive_dependents", data.get("transitive_dependencies", []))

    direction = "Dependents" if "direct_dependents" in data else "Dependencies"
    lines.append(f"## {direction}: `{file}`")
    lines.append("")
    lines.append(f"**Direct:** {stats.get('direct_count', 0)} | **Transitive:** {stats.get('transitive_count', 0)} | **Total impact:** {stats.get('total_impact', stats.get('total', 0))}")
    lines.append("")
    if direct:
        lines.append("### Direct")
        for d in direct[:20]:
            lines.append(f"- `{d}`")
        lines.append("")
    if transitive:
        lines.append("### Transitive")
        for t in transitive[:20]:
            lines.append(f"- `{t}`")
        if len(transitive) > 20:
            lines.append(f"- ... and {len(transitive) - 20} more")
        lines.append("")


def _md_validate(data: Dict, lines: list) -> None:
    """Markdown for validate command."""
    total = data.get("total_issues", 0)
    summary = data.get("summary", {})
    rec = data.get("recommendation", "")
    lines.append("## Registry Validation")
    lines.append("")
    icon = "PASS" if total == 0 else "FAIL"
    lines.append(f"**Status:** {icon} ({total} issues)")
    lines.append("")
    lines.append(f"- Missing files: {summary.get('missing_files', 0)}")
    lines.append(f"- Unregistered files: {summary.get('unregistered_files', 0)}")
    lines.append(f"- Stale references: {summary.get('stale_references', 0)}")
    lines.append(f"- Orphan entries: {summary.get('orphan_entries', 0)}")
    lines.append("")
    issues = data.get("issues", {})
    if issues:
        for cat in ["missing_files", "unregistered_files", "stale_references", "orphan_entries"]:
            items = issues.get(cat, [])
            if items:
                lines.append(f"### {cat.replace('_', ' ').title()}")
                for item in items[:10]:
                    if isinstance(item, dict):
                        lines.append(f"- `{item.get('file', item.get('path', ''))}` — {item.get('reason', '')}")
                    else:
                        lines.append(f"- `{item}`")
                if len(items) > 10:
                    lines.append(f"- ... and {len(items) - 10} more")
                lines.append("")
    if rec:
        lines.append(f"**Recommendation:** {rec}")
        lines.append("")


def _md_dataflow(data: Dict, lines: list) -> None:
    """Markdown for dataflow command."""
    stats = data.get("stats", {})
    risk = data.get("risk", "")
    source_filter = data.get("source_filter", "")
    sink_filter = data.get("sink_filter", "")
    lines.append("## Data Flow Analysis")
    lines.append("")
    lines.append(f"**Risk:** {risk}")
    if source_filter:
        lines.append(f"**Source filter:** {source_filter}")
    if sink_filter:
        lines.append(f"**Sink filter:** {sink_filter}")
    lines.append(f"- Sources: {stats.get('sources_found', 0)} | Sinks: {stats.get('sinks_found', 0)} | Sanitizers: {stats.get('sanitizers_found', 0)}")
    lines.append(f"- Violations: {stats.get('violations', 0)} | Safe paths: {stats.get('safe_paths', 0)} | Untraced: {stats.get('untraced_sources', 0)}")
    lines.append("")
    violations = data.get("violations", [])
    if violations:
        lines.append("### Violations")
        for v in violations[:10]:
            source = v.get("source", {})
            sink = v.get("sink", {})
            sev = source.get("severity", v.get("severity", ""))
            src_label = source.get("label", source.get("name", source.get("fn", "")))
            src_file = source.get("file", "")
            src_line = source.get("line", "")
            snk_label = sink.get("label", sink.get("name", sink.get("fn", "")))
            snk_file = sink.get("file", "")
            snk_line = sink.get("line", "")
            sev_str = f"[{sev.upper()}] " if sev else ""
            lines.append(f"- {sev_str}`{src_label}` (`{src_file}:{src_line}`) → `{snk_label}` (`{snk_file}:{snk_line}`)")
        if len(violations) > 10:
            lines.append(f"- ... and {len(violations) - 10} more")
        lines.append("")
    safe_paths = data.get("safe_paths", [])
    if safe_paths:
        lines.append("### Safe Paths")
        for sp in safe_paths[:5]:
            src = sp.get("source", {})
            snk = sp.get("sink", {})
            src_label = src.get("label", src.get("name", ""))
            snk_label = snk.get("label", snk.get("name", ""))
            san = sp.get("sanitizer", {})
            san_label = san.get("label", san.get("name", "unknown")) if isinstance(san, dict) else "unknown"
            lines.append(f"- `{src_label}` → `{snk_label}` (sanitized by `{san_label}`)")
        if len(safe_paths) > 5:
            lines.append(f"- ... and {len(safe_paths) - 5} more")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_test_map(data: Dict, lines: list) -> None:
    """Markdown for test-map command."""
    # Check if it's a single-function result
    fn_name = data.get("function", "")
    if fn_name:
        tested = data.get("tested", False)
        icon = "COVERED" if tested else "UNTESTED"
        lines.append(f"## Test Coverage: `{fn_name}`")
        lines.append("")
        lines.append(f"**Status:** {icon}")
        coverage = data.get("coverage", [])
        if coverage:
            for c in coverage[:10]:
                file = c.get("file", "")
                c_tested = c.get("tested", False)
                lines.append(f"- `{file}` — {'tested' if c_tested else 'untested'}")
        recs = data.get("recommendations", [])
        if recs:
            lines.append("")
            lines.append("### Recommendations")
            for r in recs[:5]:
                lines.append(f"- {r}")
        lines.append("")
        return

    # Full workspace coverage
    stats = data.get("stats", {})
    lines.append("## Test Coverage Map")
    lines.append("")
    lines.append(f"**Source files:** {stats.get('total_source_files', 0)} | **Test files:** {stats.get('total_test_files', 0)}")
    lines.append(f"**Functions:** {stats.get('total_functions', 0)} | **Tested:** {stats.get('tested_functions', 0)} | **Untested:** {stats.get('untested_functions', 0)}")
    lines.append(f"**Coverage:** {stats.get('coverage_percent', 0)}% | **Files without tests:** {stats.get('files_without_tests', 0)}")
    lines.append("")
    untested = data.get("untested_list", [])
    if untested:
        lines.append("### Untested Functions")
        for u in untested[:15]:
            if isinstance(u, dict):
                fname = u.get("name", u.get("function", ""))
                lines.append(f"- `{fname}` in `{u.get('file', '')}`")
            else:
                lines.append(f"- `{u}`")
        if len(untested) > 15:
            lines.append(f"- ... and {len(untested) - 15} more")
        lines.append("")
    files_without = data.get("files_without_tests", [])
    if files_without:
        lines.append("### Files Without Tests")
        for f in files_without[:10]:
            if isinstance(f, dict):
                lines.append(f"- `{f.get('file', f.get('path', ''))}`")
            else:
                lines.append(f"- `{f}`")
        lines.append("")
    orphan_tests = data.get("orphan_tests", [])
    if orphan_tests:
        lines.append("### Orphan Tests")
        for t in orphan_tests[:5]:
            lines.append(f"- `{t}`")
        lines.append("")


def _md_config_drift(data: Dict, lines: list) -> None:
    """Markdown for config-drift command."""
    stats = data.get("stats", {})
    drift = data.get("drift", {})
    project_type = data.get("project_type", "")
    lines.append("## Config Drift Analysis")
    lines.append("")
    if project_type:
        lines.append(f"**Project type:** {project_type}")
    lines.append(f"**Declared:** {stats.get('declared_count', 0)} | Missing: {stats.get('missing_deps', 0)} | Unused: {stats.get('unused_deps', 0)} | Dev/prod mismatch: {stats.get('dev_prod_mismatch', 0)} | Phantom: {stats.get('phantom_imports', 0)}")
    lines.append("")
    missing = drift.get("missing", [])
    if missing:
        lines.append("### Missing Dependencies")
        for m in missing[:10]:
            if isinstance(m, dict):
                name = m.get("name", m.get("package", ""))
                sev = m.get("severity", "")
                msg = m.get("message", "")[:60]
                sev_str = f"[{sev.upper()}] " if sev else ""
                lines.append(f"- {sev_str}`{name}` — {msg}")
            else:
                lines.append(f"- `{m}` — used in code but not declared")
        lines.append("")
    unused = drift.get("unused", [])
    if unused:
        lines.append("### Unused Dependencies")
        for u in unused[:10]:
            if isinstance(u, dict):
                name = u.get("name", u.get("package", ""))
                lines.append(f"- `{name}` — declared but not imported")
            else:
                lines.append(f"- `{u}` — declared but not imported")
        lines.append("")
    dev_prod = drift.get("dev_prod_mismatch", [])
    if dev_prod:
        lines.append("### Dev/Prod Mismatches")
        for d in dev_prod[:5]:
            if isinstance(d, dict):
                lines.append(f"- `{d.get('name', '')}` — {d.get('reason', '')}")
            else:
                lines.append(f"- `{d}`")
        lines.append("")
    phantom = drift.get("phantom_imports", [])
    if phantom:
        lines.append("### Phantom Imports")
        for p in phantom[:5]:
            lines.append(f"- `{p}`")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_type_infer(data: Dict, lines: list) -> None:
    """Markdown for type-infer command."""
    fn_name = data.get("function", "")
    if fn_name:
        # Single function result
        inferred = data.get("inferred_types", [])
        lines.append(f"## Type Inference: `{fn_name}`")
        lines.append("")
        lines.append(f"**Inferred types:** {data.get('count', 0)}")
        lines.append("")
        if inferred:
            for t in inferred[:15]:
                name = t.get("name", "")
                inferred_type = t.get("inferred_type", t.get("type", ""))
                confidence = t.get("confidence", "")
                lines.append(f"- `{name}`: {inferred_type} ({confidence})")
        lines.append("")
        return

    # Full workspace result
    stats = data.get("stats", {})
    lines.append("## Type Inference")
    lines.append("")
    lines.append(f"**Files analyzed:** {stats.get('files_analyzed', 0)} | **Variables typed:** {stats.get('variables_typed', 0)} | **Functions typed:** {stats.get('functions_typed', 0)} | **High confidence:** {stats.get('high_confidence', 0)}")
    lines.append("")
    type_map = data.get("type_map", {})
    if type_map:
        count = 0
        for file_path, types in type_map.items():
            if count >= 10:
                break
            if isinstance(types, dict) and types:
                lines.append(f"### `{file_path}`")
                for name, info in list(types.items())[:8]:
                    if isinstance(info, dict):
                        kind = info.get("kind", "")
                        inferred_type = info.get("inferred_type", info.get("type", ""))
                        confidence = info.get("confidence", "")
                        lines.append(f"- `{name}` ({kind}): {inferred_type} [{confidence}]")
                lines.append("")
                count += 1
    lines.append("")


def _md_ownership(data: Dict, lines: list) -> None:
    """Markdown for ownership command."""
    status = data.get("status", "")

    # No git repo
    if status == "no_git":
        lines.append("## Code Ownership")
        lines.append("")
        lines.append("**Git not available** — using file modification times as proxy")
        lines.append("")
        fallback = data.get("fallback", {})
        if fallback:
            files = fallback.get("files", [])
            stale = fallback.get("stale_count", 0)
            lines.append(f"**Stale files:** {stale}")
            for f in files[:10]:
                lines.append(f"- `{f.get('path', '')}` — last modified {f.get('last_modified_days_ago', '?')} days ago ({f.get('freshness', '')})")
            lines.append("")
        return

    # Single function
    fn_name = data.get("function", "")
    if fn_name:
        lines.append(f"## Ownership: `{fn_name}`")
        lines.append("")
        lines.append(f"**File:** `{data.get('file', '')}:{data.get('line', '')}`")
        owner = data.get("primary_owner", "")
        if owner:
            lines.append(f"**Primary owner:** {owner}")
        lines.append("")
        ownership = data.get("ownership", [])
        if ownership:
            lines.append("### Ownership Breakdown")
            for o in ownership[:5]:
                lines.append(f"- {o.get('author', '')}: {o.get('percentage', 0):.0f}% ({o.get('lines', 0)} lines)")
            lines.append("")
        age = data.get("age", {})
        if age:
            lines.append(f"**Age:** avg {age.get('average_age_days', 0)}d | median {age.get('median_age_days', 0)}d | freshness: {age.get('freshness', '')}")
            lines.append("")
        recs = data.get("recommendations", [])
        if recs:
            for r in recs[:3]:
                lines.append(f"- {r}")
            lines.append("")
        return

    # Single file
    file = data.get("file", "")
    if file and not data.get("ownership_summary"):
        lines.append(f"## Ownership: `{file}`")
        lines.append("")
        lines.append(f"**Total lines:** {data.get('total_lines', 0)} | **Stale:** {data.get('stale_percentage', 0)}%")
        lines.append("")
        ownership = data.get("ownership", [])
        if ownership:
            for o in ownership[:5]:
                lines.append(f"- {o.get('author', '')}: {o.get('percentage', 0):.0f}% ({o.get('lines', 0)} lines)")
            lines.append("")
        return

    # Full workspace
    stats = data.get("stats", {})
    ownership_summary = data.get("ownership_summary", [])
    lines.append("## Code Ownership")
    lines.append("")
    lines.append(f"**Contributors:** {stats.get('contributors', 0)} | **Files analyzed:** {stats.get('files_analyzed', 0)} | **Stale files:** {stats.get('stale_files', 0)}")
    lines.append("")
    if ownership_summary:
        lines.append("### Top Contributors")
        for o in ownership_summary[:10]:
            author = o.get("author", o.get("name", ""))
            files = o.get("files", 0)
            pct = o.get("percentage", 0)
            lines.append(f"- {author}: {pct:.0f}% ({files} files)")
        lines.append("")
    orphan_files = data.get("orphan_files", [])
    if orphan_files:
        lines.append("### Orphan Files (no recent owner)")
        for f in orphan_files[:10]:
            if isinstance(f, dict):
                lines.append(f"- `{f.get('path', f.get('file', ''))}`")
            else:
                lines.append(f"- `{f}`")
        lines.append("")


def _md_debug_leak(data: Dict, lines: list) -> None:
    """Markdown for debug-leak command."""
    stats = data.get("stats", {})
    lines.append("## Debug Leak Detection")
    lines.append("")
    lines.append(f"**Total leaks:** {stats.get('total_leaks', 0)} | **Files scanned:** {stats.get('files_scanned', 0)}")
    by_cat = stats.get("by_category", {})
    if by_cat:
        parts = [f"{k}: {v}" for k, v in by_cat.items() if v > 0]
        lines.append(f"- By category: {', '.join(parts)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    lines.append("")
    leaks = data.get("leaks", [])
    if leaks:
        lines.append("### Leaks")
        for leak in leaks[:20]:
            file = leak.get("file", "")
            line = leak.get("line", "")
            cat = leak.get("category", "")
            sev = leak.get("severity", "")
            content = leak.get("content", leak.get("match", ""))[:60]
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: `{content}`")
        if len(leaks) > 20:
            lines.append(f"- ... and {len(leaks) - 20} more")
        lines.append("")
    cleanup = data.get("cleanup_priority", [])
    if cleanup:
        lines.append("### Cleanup Priority")
        for item in cleanup[:5]:
            lines.append(f"- `{item.get('file', '')}:{item.get('line', '')}` — {item.get('category', '')}")
        lines.append("")


def _md_stack_trace(data: Dict, lines: list) -> None:
    """Markdown for stack-trace command."""
    fn_name = data.get("function", "")
    stats = data.get("stats", {})
    crash_risk = data.get("crash_risk", "")
    lines.append(f"## Stack Trace: `{fn_name}`")
    lines.append("")
    lines.append(f"**Crash risk:** {crash_risk}")
    lines.append(f"- Paths: {stats.get('total_paths', 0)} | Handled: {stats.get('handled', 0)} | Unhandled: {stats.get('unhandled', 0)} | Partial: {stats.get('partially_handled', 0)}")
    lines.append(f"- Max depth: {stats.get('max_depth_reached', 0)}")
    lines.append("")
    chains = data.get("chains", [])
    if chains:
        lines.append("### Error Chains")
        for chain in chains[:5]:
            origin = chain.get("origin", {})
            origin_fn = origin.get("fn", "")
            origin_file = origin.get("file", "")
            chain_len = chain.get("chain_length", 0)
            lines.append(f"- `{origin_fn}` (`{origin_file}`) — chain length: {chain_len}")
        lines.append("")
    propagation = data.get("propagation", [])
    if propagation:
        lines.append("### Propagation")
        for p in propagation[:10]:
            fn = p.get("fn", p.get("function", ""))
            file = p.get("file", "")
            handling = p.get("error_handling", {})
            has_handling = handling.get("has_handling", False) if isinstance(handling, dict) else handling
            status_str = "handled" if has_handling else "UNHANDLED"
            lines.append(f"- `{fn}` (`{file}`) [{status_str}]")
        if len(propagation) > 10:
            lines.append(f"- ... and {len(propagation) - 10} more")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_refactor_safe(data: Dict, lines: list) -> None:
    """Markdown for refactor-safe command."""
    name = data.get("symbol", "")
    action = data.get("action", "")
    safety = data.get("safety", "")
    stats = data.get("stats", {})
    lines.append(f"## Refactor Safety: `{name}`")
    lines.append("")
    lines.append(f"**Action:** {action} | **Safety:** {safety}")
    lines.append(f"- Total risks: {stats.get('total_risks', 0)} | Files affected: {stats.get('files_affected', 0)}")
    lines.append(f"- String refs: {stats.get('string_refs', 0)} | Dynamic access: {stats.get('dynamic_access', 0)} | Eval refs: {stats.get('eval_refs', 0)}")
    lines.append(f"- Test refs: {stats.get('test_refs', 0)} | Config refs: {stats.get('config_refs', 0)} | Doc refs: {stats.get('doc_refs', 0)}")
    lines.append("")
    risks = data.get("risks", {})
    if risks:
        for risk_type, risk_items in risks.items():
            if risk_items:
                lines.append(f"### {risk_type.replace('_', ' ').title()}")
                for item in risk_items[:10]:
                    if isinstance(item, dict):
                        lines.append(f"- `{item.get('file', '')}:{item.get('line', '')}` — {item.get('match', item.get('content', ''))[:60]}")
                    else:
                        lines.append(f"- `{item}`")
                if len(risk_items) > 10:
                    lines.append(f"- ... and {len(risk_items) - 10} more")
                lines.append("")
    files_to_update = data.get("files_to_update", [])
    if files_to_update:
        lines.append("### Files to Update")
        for f in files_to_update[:15]:
            lines.append(f"- `{f}`")
        if len(files_to_update) > 15:
            lines.append(f"- ... and {len(files_to_update) - 15} more")
        lines.append("")


def _md_env_check(data: Dict, lines: list) -> None:
    """Markdown for env-check command."""
    stats = data.get("stats", {})
    lines.append("## Environment Variable Audit")
    lines.append("")
    lines.append(f"**Total vars:** {stats.get('total_vars', 0)} | Required: {stats.get('required', 0)} | Optional: {stats.get('optional', 0)} | Undocumented: {stats.get('undocumented', 0)}")
    lines.append(f"**In .env file:** {stats.get('in_env_file', 0)} | **Files scanned:** {stats.get('files_scanned', 0)}")
    lines.append("")
    variables = data.get("variables", [])
    if variables:
        lines.append("### Variables")
        for v in variables[:20]:
            name = v.get("name", "")
            required = v.get("required", False)
            vtype = v.get("type", "")
            has_default = v.get("has_default", False)
            req_str = "REQUIRED" if required else "optional"
            default_str = " (has default)" if has_default else ""
            lines.append(f"- `{name}` [{req_str}] {vtype}{default_str}")
        if len(variables) > 20:
            lines.append(f"- ... and {len(variables) - 20} more")
        lines.append("")
    missing = data.get("missing_from_example", [])
    if missing:
        lines.append("### Missing from .env.example")
        for m in missing[:10]:
            if isinstance(m, dict):
                name = m.get("name", "")
                req = " (required)" if m.get("is_required") else ""
                lines.append(f"- `{name}`{req}")
            else:
                lines.append(f"- `{m}`")
        lines.append("")
    required_no_fb = data.get("required_without_fallback", [])
    if required_no_fb:
        lines.append("### Required Without Fallback")
        for r in required_no_fb[:10]:
            if isinstance(r, dict):
                name = r.get("name", "")
                lines.append(f"- `{name}`")
            else:
                lines.append(f"- `{r}`")
        lines.append("")
    naming = data.get("naming_inconsistencies", [])
    if naming:
        lines.append("### Naming Inconsistencies")
        for n in naming[:5]:
            lines.append(f"- {n}")
        lines.append("")
    env_files = data.get("env_files", [])
    if env_files:
        lines.append("### Env Files")
        for ef in env_files[:5]:
            if isinstance(ef, dict):
                lines.append(f"- `{ef.get('path', '')}` ({ef.get('type', '')})")
            else:
                lines.append(f"- `{ef}`")
        lines.append("")


def _md_state_map(data: Dict, lines: list) -> None:
    """Markdown for state-map command."""
    stats = data.get("stats", {})
    lines.append("## State Map")
    lines.append("")
    lines.append(f"**Stores:** {stats.get('total_stores', 0)} | **Slices:** {stats.get('total_slices', 0)} | **Files scanned:** {stats.get('files_scanned', 0)}")
    fws = stats.get("frameworks_detected", [])
    if fws:
        lines.append(f"**Frameworks:** {', '.join(fws)}")
    by_type = stats.get("by_type", {})
    if by_type:
        parts = [f"{k}: {v}" for k, v in by_type.items() if v > 0]
        lines.append(f"- By type: {', '.join(parts)}")
    lines.append("")
    stores = data.get("stores", [])
    if stores:
        lines.append("### Stores")
        for store in stores[:15]:
            name = store.get("name", "")
            stype = store.get("type", "")
            framework = store.get("framework", "")
            defined = store.get("defined_in", "")
            line = store.get("line", "")
            fw_str = f" ({framework})" if framework else ""
            lines.append(f"- `{name}` [{stype}]{fw_str} — `{defined}:{line}`")
            slices = store.get("slices", [])
            if slices:
                for s in slices[:3]:
                    s_name = s.get("name", "") if isinstance(s, dict) else str(s)
                    lines.append(f"  - slice: `{s_name}`")
            actions = store.get("actions", [])
            if actions:
                for a in actions[:3]:
                    a_name = a.get("name", "") if isinstance(a, dict) else str(a)
                    lines.append(f"  - action: `{a_name}`")
        if len(stores) > 15:
            lines.append(f"- ... and {len(stores) - 15} more")
        lines.append("")
    flow = data.get("state_flow", [])
    if flow:
        lines.append("### State Flow")
        for f in flow[:10]:
            from_file = f.get("from", "")
            to_file = f.get("to", "")
            via = f.get("via", "")
            lines.append(f"- `{from_file}` → `{to_file}" + (f"` via `{via}" if via else "`"))
        if len(flow) > 10:
            lines.append(f"- ... and {len(flow) - 10} more")
        lines.append("")


def _md_vuln_scan(data: Dict, lines: list) -> None:
    """Markdown for vuln-scan command."""
    stats = data.get("stats", {})
    risk = data.get("risk", "")
    severity_filter = data.get("severity_filter", "")
    lines.append("## Vulnerability Scan")
    lines.append("")
    lines.append(f"**Risk:** {risk}")
    if severity_filter:
        lines.append(f"**Severity filter:** {severity_filter}")
    lines.append(f"- Total vulnerabilities: {stats.get('total_vulnerabilities', 0)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    by_eco = stats.get("by_ecosystem", {})
    if by_eco:
        parts = [f"{k}: {v}" for k, v in by_eco.items() if v > 0]
        lines.append(f"- By ecosystem: {', '.join(parts)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Findings")
        for f in findings[:15]:
            sev = f.get("severity", "")
            package = f.get("package", f.get("dependency", ""))
            cve = f.get("cve", f.get("vulnerability_id", ""))
            title = f.get("title", f.get("description", ""))[:60]
            lines.append(f"- [{sev.upper()}] `{package}` — {cve}: {title}")
        if len(findings) > 15:
            lines.append(f"- ... and {len(findings) - 15} more")
        lines.append("")
    audit = data.get("audit_available", False)
    if not audit:
        lines.append("**Note:** No lockfile found — results are based on manifest analysis only.")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_perf_hint(data: Dict, lines: list) -> None:
    """Markdown for perf-hint command."""
    stats = data.get("stats", {})
    risk = data.get("risk", "")
    sev_filter = data.get("severity_filter", "")
    cat_filter = data.get("category_filter", "")
    lines.append("## Performance Hints")
    lines.append("")
    lines.append(f"**Risk:** {risk}")
    if sev_filter:
        lines.append(f"**Severity filter:** {sev_filter}")
    if cat_filter:
        lines.append(f"**Category filter:** {cat_filter}")
    lines.append(f"- Total hints: {stats.get('total_hints', 0)}")
    by_cat = stats.get("by_category", {})
    if by_cat:
        parts = [f"{k}: {v}" for k, v in by_cat.items() if v > 0]
        lines.append(f"- By category: {', '.join(parts)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Findings")
        for f in findings[:15]:
            sev = f.get("severity", "")
            cat = f.get("category", "")
            file = f.get("file", "")
            line = f.get("line", "")
            msg = f.get("message", f.get("description", ""))[:60]
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: {msg}")
        if len(findings) > 15:
            lines.append(f"- ... and {len(findings) - 15} more")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_css_deep(data: Dict, lines: list) -> None:
    """Markdown for css-deep command."""
    stats = data.get("stats", {})
    sev_filter = data.get("severity_filter", "")
    lines.append("## Deep CSS Analysis")
    lines.append("")
    if sev_filter:
        lines.append(f"**Severity filter:** {sev_filter}")
    lines.append(f"- Total issues: {stats.get('total_issues', 0)}")
    by_cat = stats.get("by_category", {})
    if by_cat:
        parts = [f"{k}: {v}" for k, v in by_cat.items() if v > 0]
        lines.append(f"- By category: {', '.join(parts)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    lines.append(f"- CSS files: {stats.get('css_files_scanned', 0)} | HTML/JS files: {stats.get('html_js_files_scanned', 0)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Findings")
        for f in findings[:15]:
            sev = f.get("severity", "")
            cat = f.get("category", "")
            file = f.get("file", "")
            line = f.get("line", "")
            name = f.get("name", "")
            msg = f.get("message", "")[:60]
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: {name} {msg}")
        if len(findings) > 15:
            lines.append(f"- ... and {len(findings) - 15} more")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_a11y(data: Dict, lines: list) -> None:
    """Markdown for a11y command."""
    stats = data.get("stats", {})
    lines.append("## Accessibility Audit")
    lines.append("")
    lines.append(f"- Total issues: {stats.get('total_issues', 0)} | Files scanned: {stats.get('files_scanned', 0)}")
    by_cat = stats.get("by_category", {})
    if by_cat:
        parts = [f"{k}: {v}" for k, v in by_cat.items() if v > 0]
        lines.append(f"- By category: {', '.join(parts)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    lines.append("")
    issues = data.get("issues", [])
    if issues:
        lines.append("### Issues")
        for issue in issues[:20]:
            sev = issue.get("severity", "")
            cat = issue.get("category", "")
            file = issue.get("file", "")
            line = issue.get("line", "")
            msg = issue.get("message", "")[:80]
            wcag = issue.get("wcag", "")
            wcag_str = f" (WCAG {wcag})" if wcag else ""
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: {msg}{wcag_str}")
        if len(issues) > 20:
            lines.append(f"- ... and {len(issues) - 20} more")
        lines.append("")
    wcag_map = data.get("wcag_mapping", {})
    if wcag_map:
        lines.append("### WCAG Mapping")
        for criterion, count in wcag_map.items():
            lines.append(f"- {criterion}: {count} issue(s)")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_regex_audit(data: Dict, lines: list) -> None:
    """Markdown for regex-audit command."""
    stats = data.get("stats", {})
    lines.append("## Regex Audit")
    lines.append("")
    lines.append(f"- Total patterns: {stats.get('total_patterns', 0)} | Vulnerable: {stats.get('vulnerable', 0)} | Files scanned: {stats.get('files_scanned', 0)}")
    by_cat = stats.get("by_category", {})
    if by_cat:
        parts = [f"{k}: {v}" for k, v in by_cat.items() if v > 0]
        lines.append(f"- By category: {', '.join(parts)}")
    by_sev = stats.get("by_severity", {})
    if by_sev:
        parts = [f"{k}: {v}" for k, v in by_sev.items() if v > 0]
        lines.append(f"- By severity: {', '.join(parts)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Vulnerable Patterns")
        for f in findings[:15]:
            sev = f.get("severity", "")
            cat = f.get("category", "")
            file = f.get("file", "")
            line = f.get("line", "")
            pattern = f.get("pattern", "")[:40]
            msg = f.get("message", "")[:60]
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: `/{pattern}/` {msg}")
        if len(findings) > 15:
            lines.append(f"- ... and {len(findings) - 15} more")
        lines.append("")
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("### Recommendations")
        for r in recommendations[:5]:
            lines.append(f"- {r}")
        lines.append("")


def _md_ask(data: Dict, lines: list) -> None:
    """Markdown for ask command — shows interpretation then delegates to sub-formatter."""
    interp = data.get("query_interpretation", {})

    # Handle unknown_query or error status
    if data.get("status") == "unknown_query":
        lines.append("## Ask")
        lines.append("")
        lines.append(f"**Question:** {data.get('question', '')}")
        lines.append(f"**Status:** Could not interpret query")
        suggestion = data.get("suggestion", "")
        if suggestion:
            lines.append(f"**Suggestion:** {suggestion}")
        lines.append("")
        return

    if data.get("status") == "error" and "error" in data and "interpreted_as" in data:
        lines.append("## Ask")
        lines.append("")
        lines.append(f"**Question:** {data.get('question', interp.get('question', ''))}")
        lines.append(f"**Interpreted as:** {data.get('interpreted_as', '')}")
        lines.append(f"**Error:** {data.get('error', '')}")
        lines.append("")
        return

    # Show interpretation header
    lines.append("## Ask")
    lines.append("")
    question = interp.get("question", "")
    interpreted_as = interp.get("interpreted_as", "")
    confidence = interp.get("confidence", "")
    if question:
        lines.append(f"**Question:** {question}")
    if interpreted_as:
        lines.append(f"**Interpreted as:** `{interpreted_as}`")
    if confidence:
        lines.append(f"**Confidence:** {confidence}")
    lines.append("")

    # Delegate to the appropriate sub-formatter by stripping query_interpretation
    # and routing to the correct formatter
    sub_data = {k: v for k, v in data.items() if k != "query_interpretation"}
    sub_command = interpreted_as

    # Map the interpreted command to the right formatter
    formatter_map = {
        "scan": _md_scan,
        "query": _md_query,
        "context": _md_context,
        "outline": _md_outline,
        "impact": _md_impact,
        "trace": _md_trace,
        "smell": _md_smell,
        "dead-code": _md_dead_code,
        "circular": _md_circular,
        "handbook": _md_handbook,
        "entrypoints": _md_entrypoints,
        "api-map": _md_api_map,
        "complexity": _md_complexity,
        "secrets": _md_secrets,
        "side-effect": _md_side_effect,
        "symbols": _md_symbols,
        "test-map": _md_test_map,
        "perf-hint": _md_perf_hint,
        "vuln-scan": _md_vuln_scan,
        "env-check": _md_env_check,
        "debug-leak": _md_debug_leak,
        "state-map": _md_state_map,
        "dependents": _md_dependents,
    }

    formatter = formatter_map.get(sub_command)
    if formatter:
        formatter(sub_data, lines)
    else:
        _md_generic(sub_data, lines)

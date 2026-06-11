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
    else:
        # Generic markdown for any command
        _md_generic(data, lines)

    return "\n".join(lines)


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
                    for chain in dir_chains[:10]:
                        if isinstance(chain, dict):
                            path = chain.get("path", [])
                            if path:
                                lines.append(f"- {' → '.join(str(p) for p in path)}")
                            else:
                                fn = chain.get("fn", "")
                                file = chain.get("file", "")
                                depth = chain.get("depth", "")
                                lines.append(f"- `{' → ' * depth}{fn}` ({file})")
                        elif isinstance(chain, list):
                            lines.append(f"- {' → '.join(str(p) for p in chain)}")
                        else:
                            lines.append(f"- {chain}")
                    lines.append("")
        elif isinstance(chains, list):
            for chain in chains[:10]:
                if isinstance(chain, dict):
                    path = chain.get("path", [])
                    lines.append(f"- {' → '.join(str(p) for p in path)}")
                elif isinstance(chain, list):
                    lines.append(f"- {' → '.join(str(p) for p in chain)}")
                else:
                    lines.append(f"- {chain}")
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
    lines.append(f"- Total dead: {stats.get('total_dead', 0)}")
    lines.append(f"- Unreachable: {stats.get('unreachable', 0)} | Unused exports: {stats.get('unused_exports', 0)} | Zombie CSS: {stats.get('zombie_css', 0)}")
    removal_safety = data.get("removal_safety", "")
    if removal_safety:
        lines.append(f"- **Removal safety:** {removal_safety}")
    lines.append("")
    items = data.get("dead_items", data.get("items", []))
    if items:
        lines.append("### Items")
        for item in items[:15]:
            file = item.get("file", "")
            line = item.get("line", "")
            dtype = item.get("type", item.get("category", ""))
            name = item.get("name", item.get("fn", ""))
            lines.append(f"- `{file}:{line}` — {dtype}: {name}")
        lines.append("")


def _md_circular(data: Dict, lines: list) -> None:
    """Markdown for circular command."""
    chains = data.get("chains", [])
    lines.append("## Circular Dependencies")
    lines.append("")
    lines.append(f"**Found:** {len(chains)} circular chain(s)")
    lines.append("")
    for chain in chains[:10]:
        path = chain.get("path", chain) if isinstance(chain, dict) else chain
        if isinstance(path, list):
            lines.append(f"- {' → '.join(str(p) for p in path)}")
        else:
            lines.append(f"- {path}")
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
        lines.append(f"- [{etype}] `{file}:{line}` — {label}{extra}")
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
        for f in findings[:15]:
            lines.append(f"- [{f.get('severity', '').upper()}] `{f.get('file', '')}:{f.get('line', '')}` — {f.get('type', '')}")
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

# CodeLens — AI-Native Code Intelligence

**VS Code Extension for the [CodeLens](https://github.com/Wolfvin/CodeLens) code analysis platform.**

## Features

- **Diagnostics on Save** — Automatically scans Python, JavaScript, and TypeScript files when you save or open them, surfacing issues as VS Code diagnostics.
- **Quick Fixes** — Right-click any CodeLens diagnostic and choose "Auto-fix with CodeLens" to apply confidence-scored fixes. Supports batch "Fix All" mode.
- **Guard Pre-Save Checks** — Optional pre-save safety verification that warns you before saving files with critical issues (enable via `codelens.enableGuard`).
- **Workspace Scan** — Run a full workspace scan with progress indicator via the Command Palette (`CodeLens: Scan Workspace`).
- **Status Bar Health** — Shows a color-coded health indicator (green/yellow/red) with issue counts. Click to open the Problems panel.
- **SARIF Integration** — All diagnostics are derived from SARIF v2.1.0 output, compatible with GitHub Advanced Security.
- **Taint Path Visualization** — Diagnostics from taint analysis include source-to-sink data flow information.

## Commands

| Command | Keybinding | Description |
|---------|-----------|-------------|
| `CodeLens: Scan Workspace` | `Ctrl+Shift+F6` | Run a full workspace scan |
| `CodeLens: Fix Issues` | `Ctrl+Shift+F7` | Open fix panel for current file |
| `CodeLens: Guard Check` | — | Run pre-save guard on current file |
| `CodeLens: Open Dashboard` | — | Generate and open HTML dashboard |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `codelens.path` | `""` | Path to `codelens.py`. Auto-detects if empty. |
| `codelens.autoScan` | `true` | Auto-scan on save and open |
| `codelens.minSeverity` | `"medium"` | Minimum severity to report |
| `codelens.enableGuard` | `false` | Enable pre-save guard checks |
| `codelens.scanCommands` | `"dead-code,secrets,smell,complexity"` | Commands to run on scan |
| `codelens.maxFindings` | `100` | Max findings to display |
| `codelens.debounceMs` | `2000` | Min ms between auto-scans |
| `codelens.fixMinConfidence` | `0.8` | Min confidence for auto-fix suggestions |

## Prerequisites

Install the CodeLens CLI:

```bash
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens
pip install -e .
```

Or set `codelens.path` to point to your `codelens.py` file.

## How It Works

1. On save/open, the extension runs `codelens check --sarif --commands <commands> <workspace>`
2. SARIF v2.1.0 output is parsed into VS Code `Diagnostic` objects
3. Diagnostics appear in the Problems panel with severity-mapped icons
4. Code actions provide quick-fix and guard-check options
5. The status bar shows aggregate health at a glance

## Supported Languages

- Python (`.py`)
- JavaScript (`.js`, `.jsx`)
- TypeScript (`.ts`, `.tsx`)

## License

MIT

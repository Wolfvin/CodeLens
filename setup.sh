#!/usr/bin/env bash
# CodeLens v2 Setup Script — Tree-sitter Edition
# Installs required Python dependencies including tree-sitter grammars
#
# Issue #64 Phase 2: appends a Markdown + JSON session log entry to
# ``~/.codelens/session.md`` and ``~/.codelens/session.json`` on every
# run. View with ``codelens sessions``. Rotation is handled by the
# ``sessions`` command (keeps last 50 when log exceeds 1 MB).

set -e

# ─── Session log setup (issue #64 Phase 2) ────────────────────
# Capture start time and metadata BEFORE any work, so we can record
# duration and partial-failure state at the end.
SESSION_START_EPOCH=$(date +%s)
SESSION_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SESSION_PYTHON_VERSION=""
SESSION_OS=""
SESSION_ARCH=""
SESSION_WARNINGS=""
SESSION_ERRORS=""
SESSION_DEPS_INSTALLED=""

# Detect Python version early (we need it for the session record).
if command -v python3 &> /dev/null; then
    SESSION_PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null || echo "unknown")
fi
SESSION_OS=$(uname -s 2>/dev/null || echo "unknown")
SESSION_ARCH=$(uname -m 2>/dev/null || echo "unknown")

# CodeLens config dir — matches DEFAULT_CONFIG_DIR in
# scripts/commands/sessions.py. Override via CODELENS_CONFIG_DIR env
# var (useful for testing).
CODELENS_CONFIG_DIR="${CODELENS_CONFIG_DIR:-$HOME/.codelens}"
mkdir -p "$CODELENS_CONFIG_DIR"
SESSION_MD="$CODELENS_CONFIG_DIR/session.md"
SESSION_JSON="$CODELENS_CONFIG_DIR/session.json"

# Initialize the Markdown log with a header if it doesn't exist yet.
if [ ! -f "$SESSION_MD" ]; then
    echo "# CodeLens install sessions" > "$SESSION_MD"
    echo "" >> "$SESSION_MD"
fi

echo "[CodeLens] Setting up dependencies (Tree-sitter Edition)..."

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[CodeLens] ERROR: python3 not found. Please install Python 3.8+."
    SESSION_ERRORS="python3 not found"
    _codelens_write_session_log 1
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[CodeLens] Python version: $PYTHON_VERSION"

# Install core tree-sitter
echo "[CodeLens] Installing tree-sitter core..."
if pip3 install tree-sitter --quiet 2>/dev/null || pip install tree-sitter --quiet 2>/dev/null; then
    SESSION_DEPS_INSTALLED="${SESSION_DEPS_INSTALLED}tree-sitter "
else
    SESSION_WARNINGS="${SESSION_WARNINGS}tree-sitter install failed; "
fi

# Install grammar packages
echo "[CodeLens] Installing tree-sitter grammars..."
GRAMMARS=(
    "tree-sitter-html"
    "tree-sitter-css"
    "tree-sitter-javascript"
    "tree-sitter-typescript"
    "tree-sitter-rust"
    "tree-sitter-python"
)

for grammar in "${GRAMMARS[@]}"; do
    echo "[CodeLens]   Installing $grammar..."
    if pip3 install "$grammar" --quiet 2>/dev/null || pip install "$grammar" --quiet 2>/dev/null; then
        SESSION_DEPS_INSTALLED="${SESSION_DEPS_INSTALLED}${grammar} "
    else
        echo "[CodeLens]   Warning: $grammar install failed."
        SESSION_WARNINGS="${SESSION_WARNINGS}${grammar} install failed; "
    fi
done

# Install watchdog for file watching (optional but recommended)
echo "[CodeLens] Installing watchdog (for real-time file watching)..."
if pip3 install watchdog --quiet 2>/dev/null || pip install watchdog --quiet 2>/dev/null; then
    SESSION_DEPS_INSTALLED="${SESSION_DEPS_INSTALLED}watchdog "
else
    echo "[CodeLens] Warning: watchdog install failed. File watcher will use polling mode."
    SESSION_WARNINGS="${SESSION_WARNINGS}watchdog install failed; "
fi

# Verify core modules work
echo "[CodeLens] Verifying codelens CLI..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! python3 "$SCRIPT_DIR/scripts/codelens.py" --help > /dev/null 2>&1; then
    SESSION_ERRORS="${SESSION_ERRORS}codelens CLI verification failed; "
fi

# Test tree-sitter grammars
echo "[CodeLens] Testing tree-sitter grammars..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRAMMAR_TEST_OUTPUT=$(PYTHONPATH="$SCRIPT_DIR/scripts:$PYTHONPATH" python3 -c "
from grammar_loader import GrammarLoader
loader = GrammarLoader()
available = loader.available_languages()
print(f'  Available grammars: {available}')
if len(available) < 3:
    print('  WARNING: Some grammars failed to load.')
" 2>&1) || SESSION_WARNINGS="${SESSION_WARNINGS}grammar test failed; "
echo "$GRAMMAR_TEST_OUTPUT"

# Detect configured AI agent integrations (best-effort, non-fatal).
AGENTS_DETECTED=""
[ -d "$HOME/.claude" ] && AGENTS_DETECTED="${AGENTS_DETECTED}claude-code "
[ -d "$HOME/.cursor" ] && AGENTS_DETECTED="${AGENTS_DETECTED}cursor "
[ -d "$HOME/.continue" ] && AGENTS_DETECTED="${AGENTS_DETECTED}continue "

echo ""
echo "[CodeLens] Setup complete!"
echo "[CodeLens] Supported languages: HTML, CSS, JS, TS/TSX, Rust, Python"
echo "[CodeLens] Supported frameworks: React/Next.js, Vue, Svelte, Tailwind CSS"
echo ""
echo "[CodeLens] Quick start:"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py init /path/to/workspace"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py scan /path/to/workspace"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py query 'btn-primary' /path/to/workspace"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py list /path/to/workspace --filter dead"

# ─── Write session log entry (issue #64 Phase 2) ──────────────
# Define a helper function so we can call it from the error path
# above (python3-not-found) AND from the normal-success path here.
# The function uses ``date`` to compute duration and writes to both
# the Markdown log and the JSON sidecar.
_codelens_write_session_log() {
    local exit_code="$1"
    local end_epoch=$(date +%s)
    local duration=$((end_epoch - SESSION_START_EPOCH))

    # Trim trailing whitespace from accumulated strings.
    local deps=$(echo "$SESSION_DEPS_INSTALLED" | xargs)
    local warns=$(echo "$SESSION_WARNINGS" | xargs)
    local errs=$(echo "$SESSION_ERRORS" | xargs)
    local agents=$(echo "$AGENTS_DETECTED" | xargs)

    # Append to Markdown log.
    {
        echo "## ${SESSION_START_ISO} — setup"
        echo ""
        echo "- **duration_sec**: ${duration}"
        echo "- **exit_code**: ${exit_code}"
        echo "- **python**: ${SESSION_PYTHON_VERSION}"
        echo "- **os**: ${SESSION_OS}"
        echo "- **arch**: ${SESSION_ARCH}"
        echo "- **agents_detected**: ${agents}"
        echo "- **deps_installed**: ${deps}"
        [ -n "$warns" ] && echo "- **warnings**: ${warns}"
        [ -n "$errs" ] && echo "- **errors**: ${errs}"
        echo ""
    } >> "$SESSION_MD"

    # Append to JSON sidecar. We use Python here because bash doesn't
    # have native JSON support, and we want the sidecar to be a valid
    # JSON array (not JSONL). Python is guaranteed to be available
    # at this point — we checked at the top of the script.
    if [ -n "$SESSION_PYTHON_VERSION" ] && [ "$SESSION_PYTHON_VERSION" != "unknown" ]; then
        python3 - "$SESSION_JSON" "$SESSION_START_ISO" "$duration" "$exit_code" \
            "$SESSION_PYTHON_VERSION" "$SESSION_OS" "$SESSION_ARCH" \
            "$agents" "$deps" "$warns" "$errs" <<'PYEOF' 2>/dev/null || true
import json, os, sys
path = sys.argv[1]
entry = {
    "timestamp": sys.argv[2],
    "duration_sec": int(sys.argv[3]),
    "exit_code": int(sys.argv[4]),
    "python": sys.argv[5],
    "os": sys.argv[6],
    "arch": sys.argv[7],
    "agents_detected": sys.argv[8].split() if sys.argv[8] else [],
    "deps_installed": sys.argv[9].split() if sys.argv[9] else [],
    "warnings": sys.argv[10] if sys.argv[10] else None,
    "errors": sys.argv[11] if sys.argv[11] else None,
    "title": "setup",
}
# Load existing sessions (if any), append, write back.
sessions = []
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            sessions = data
    except (OSError, json.JSONDecodeError):
        pass
sessions.append(entry)
with open(path, "w", encoding="utf-8") as f:
    json.dump(sessions, f, indent=2, ensure_ascii=False)
PYEOF
    fi
}

_codelens_write_session_log 0

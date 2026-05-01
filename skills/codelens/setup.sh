#!/usr/bin/env bash
# CodeLens v2 Setup Script — Tree-sitter Edition
# Installs required Python dependencies including tree-sitter grammars

set -e

echo "[CodeLens] Setting up dependencies (Tree-sitter Edition)..."

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[CodeLens] ERROR: python3 not found. Please install Python 3.8+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[CodeLens] Python version: $PYTHON_VERSION"

# Install core tree-sitter
echo "[CodeLens] Installing tree-sitter core..."
pip3 install tree-sitter --quiet 2>/dev/null || pip install tree-sitter --quiet 2>/dev/null

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
    pip3 install "$grammar" --quiet 2>/dev/null || pip install "$grammar" --quiet 2>/dev/null || echo "[CodeLens]   Warning: $grammar install failed."
done

# Install watchdog for file watching (optional but recommended)
echo "[CodeLens] Installing watchdog (for real-time file watching)..."
pip3 install watchdog --quiet 2>/dev/null || pip install watchdog --quiet 2>/dev/null || echo "[CodeLens] Warning: watchdog install failed. File watcher will use polling mode."

# Verify core modules work
echo "[CodeLens] Verifying codelens CLI..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/scripts/codelens.py" --help

# Test tree-sitter grammars
echo "[CodeLens] Testing tree-sitter grammars..."
python3 -c "
from grammar_loader import GrammarLoader
loader = GrammarLoader()
available = loader.available_languages()
print(f'  Available grammars: {available}')
if len(available) < 3:
    print('  WARNING: Some grammars failed to load.')
"

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

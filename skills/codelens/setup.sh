#!/usr/bin/env bash
# CodeLens Setup Script
# Installs required Python dependencies

set -e

echo "[CodeLens] Setting up dependencies..."

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[CodeLens] ERROR: python3 not found. Please install Python 3.8+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[CodeLens] Python version: $PYTHON_VERSION"

# Install watchdog for file watching (optional but recommended)
echo "[CodeLens] Installing watchdog (for real-time file watching)..."
pip3 install watchdog --quiet 2>/dev/null || pip install watchdog --quiet 2>/dev/null || echo "[CodeLens] Warning: watchdog install failed. File watcher will use polling mode."

# Verify core modules work
echo "[CodeLens] Verifying codelens CLI..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/scripts/codelens.py" --help

echo ""
echo "[CodeLens] Setup complete!"
echo "[CodeLens] Usage:"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py scan /path/to/workspace"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py query 'name' /path/to/workspace"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py list /path/to/workspace --domain all --filter all"
echo "  python3 $SCRIPT_DIR/scripts/codelens.py watch /path/to/workspace"

#!/usr/bin/env bash
set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     K.A-purn-tui - One-Click Installer      ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 not found. Install Python 3.10+ first."
    exit 1
fi
echo "[OK] Python found: $(python3 --version)"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo ""
    echo "[1/4] Creating virtual environment .venv ..."
    python3 -m venv .venv
else
    echo "[OK] Virtual environment already exists"
fi

# Activate
echo ""
echo "[2/4] Activating virtual environment ..."
source .venv/bin/activate

# Upgrade pip
echo ""
echo "[3/4] Upgrading pip ..."
pip install --upgrade pip --quiet

# Install deps
echo ""
echo "[4/4] Installing project dependencies ..."
pip install -e ".[dev]" --quiet

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║           Installation Complete!             ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Usage:"
echo "  1. export DEEPSEEK_API_KEY=sk-your-key-here"
echo "  2. source .venv/bin/activate && ka-purn-tui"
echo "  3. /mode novel"
echo ""
echo "See README.md and docs/ARCHITECTURE.md for docs."
echo "═══════════════════════════════════════════════"

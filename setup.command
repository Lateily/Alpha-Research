#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  AR Equity Research Platform — One-Click Setup
#  Double-click this file on Mac to install & launch
# ═══════════════════════════════════════════════════════════════

cd "$(dirname "$0")"
echo ""
echo "══════════════════════════════════════════════"
echo "  AR Equity Research Platform"
echo "  Setting up..."
echo "══════════════════════════════════════════════"
echo ""

# Check Node.js
if ! command -v node &>/dev/null; then
  echo "❌ Node.js not found. Installing via Homebrew..."
  if ! command -v brew &>/dev/null; then
    echo "Installing Homebrew first..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  brew install node
fi

echo "✓ Node.js $(node -v)"
echo ""

# Install dependencies
echo "Installing dependencies..."
npm install
echo ""

# Launch dev server
echo "══════════════════════════════════════════════"
echo "  ✓ Launching platform..."
echo "  Open: http://localhost:5173"
echo "  Press Ctrl+C to stop"
echo "══════════════════════════════════════════════"
echo ""
npm run dev

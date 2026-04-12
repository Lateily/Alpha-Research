#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  AR Equity Research Platform — Build for Deployment
#  Double-click this file on Mac to build static files
# ═══════════════════════════════════════════════════════════════

cd "$(dirname "$0")"
echo ""
echo "══════════════════════════════════════════════"
echo "  Building for production..."
echo "══════════════════════════════════════════════"
echo ""

# Install if needed
[ ! -d "node_modules" ] && npm install

# Build
npm run build

echo ""
echo "══════════════════════════════════════════════"
echo "  ✓ Build complete!"
echo ""
echo "  Static files are in: ./dist/"
echo ""
echo "  Deploy options:"
echo "  1. Vercel:  npx vercel ./dist"
echo "  2. GitHub Pages: push dist/ to gh-pages branch"
echo "  3. Netlify: drag dist/ folder to netlify.com"
echo "  4. Any web server: just serve the dist/ folder"
echo "══════════════════════════════════════════════"
echo ""

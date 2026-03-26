#!/bin/bash

# Modal Scripts CLI - Setup Script
# This script installs dependencies and sets up the CLI

set -e

echo ""
echo "🚀 Modal Scripts CLI Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if bun is installed
if ! command -v bun &> /dev/null; then
    echo "❌ Bun is not installed"
    echo ""
    echo "Please install Bun first:"
    echo "  curl -fsSL https://bun.sh/install | bash"
    echo ""
    echo "Or visit: https://bun.sh"
    exit 1
fi

echo "✓ Bun found: $(bun --version)"

# Check if zig is installed (required for OpenTUI)
if ! command -v zig &> /dev/null; then
    echo "⚠️  Zig is not installed (required for OpenTUI)"
    echo ""
    echo "Please install Zig first:"
    echo "  macOS:   brew install zig"
    echo "  Linux:   Download from https://ziglang.org/download/"
    echo "  Windows: Download from https://ziglang.org/download/"
    echo ""
    exit 1
fi

echo "✓ Zig found: $(zig version)"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
bun install

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "✓ Dependencies installed successfully"
echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "✓ Created .env file"
    echo ""
    echo "⚠️  Please edit .env to configure your scripts directory:"
    echo "   MODAL_SCRIPTS_DIR=/path/to/your/scripts"
    echo ""
else
    echo "✓ .env file already exists"
    echo ""
fi

# Success message
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "To run the CLI:"
echo "  bun run dev"
echo ""
echo "Or with a custom scripts directory:"
echo "  MODAL_SCRIPTS_DIR=/path/to/scripts bun run dev"
echo ""
echo "For help:"
echo "  bun run dev --help"
echo ""

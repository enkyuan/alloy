#!/bin/bash
# Setup environment configuration for Modal iOS app

CONFIG_FILE="apps/modal/Config.xcconfig"
EXAMPLE_FILE="apps/modal/Config.xcconfig.example"

echo "🔧 Setting up Modal environment configuration..."

# Check if config already exists
if [ -f "$CONFIG_FILE" ]; then
    echo "⚠️  Config.xcconfig already exists!"
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Setup cancelled."
        exit 1
    fi
fi

# Copy example to config
if [ -f "$EXAMPLE_FILE" ]; then
    cp "$EXAMPLE_FILE" "$CONFIG_FILE"
    echo "✅ Created Config.xcconfig from template"
else
    echo "❌ Error: Config.xcconfig.example not found"
    exit 1
fi

echo ""
echo "📝 Please edit apps/modal/Config.xcconfig with your values:"
echo "   - API_BASE_URL (your ngrok or backend URL)"
echo "   - WEBSOCKET_URL (your WebSocket URL)"
echo "   - SUPABASE_URL (your Supabase project URL)"
echo "   - SUPABASE_ANON_KEY (your Supabase anon key)"
echo ""
echo "🔗 Next steps:"
echo "   1. Edit Config.xcconfig with your actual values"
echo "   2. Open modal.xcodeproj in Xcode"
echo "   3. Link Config.xcconfig to your build configurations"
echo "      (See apps/modal/README_ENV.md for detailed instructions)"
echo ""
echo "✨ Done! Your environment is ready to configure."

#!/bin/bash

# Check if Config.xcconfig is properly linked in Xcode project

echo "🔍 Checking Xcode configuration..."

PROJECT_FILE="apps/modal/modal.xcodeproj/project.pbxproj"

if [ ! -f "$PROJECT_FILE" ]; then
    echo "❌ Could not find project.pbxproj"
    exit 1
fi

echo ""
echo "📋 Checking if Config.xcconfig is referenced in project..."

if grep -q "Config.xcconfig" "$PROJECT_FILE"; then
    echo "✅ Config.xcconfig is referenced in the project"
else
    echo "❌ Config.xcconfig is NOT referenced in the project"
    echo ""
    echo "You need to add it to Xcode:"
    echo "1. Right-click on 'modal' folder in Xcode"
    echo "2. Select 'Add Files to modal...'"
    echo "3. Navigate to apps/modal/Config.xcconfig"
    echo "4. Click 'Add'"
    exit 1
fi

echo ""
echo "📋 Checking build configurations..."

# Check if configurations reference the xcconfig
if grep -q "baseConfigurationReference.*Config.xcconfig" "$PROJECT_FILE"; then
    echo "✅ Build configurations are using Config.xcconfig"
else
    echo "⚠️  Build configurations may not be linked to Config.xcconfig"
    echo ""
    echo "To link the config file:"
    echo "1. Open modal.xcodeproj in Xcode"
    echo "2. Select the modal PROJECT (not target) in the navigator"
    echo "3. Go to the Info tab"
    echo "4. Under 'Configurations', for BOTH Debug and Release:"
    echo "   - Click on 'modal' (the row, not the disclosure arrow)"
    echo "   - In the dropdown that appears, select 'Config'"
fi

echo ""
echo "📋 Checking Config.xcconfig values..."

if [ -f "apps/modal/Config.xcconfig" ]; then
    echo "✅ Config.xcconfig exists"
    echo ""
    echo "Current values:"
    grep "^API_BASE_URL" apps/modal/Config.xcconfig || echo "❌ API_BASE_URL not set"
    grep "^WEBSOCKET_URL" apps/modal/Config.xcconfig || echo "❌ WEBSOCKET_URL not set"
    grep "^SUPABASE_URL" apps/modal/Config.xcconfig || echo "❌ SUPABASE_URL not set"
else
    echo "❌ Config.xcconfig does not exist!"
    echo ""
    echo "Run: cp apps/modal/Config.xcconfig.example apps/modal/Config.xcconfig"
fi

echo ""
echo "================================"
echo "📝 Manual Steps Required:"
echo "================================"
echo ""
echo "1. Open Xcode: open apps/modal/modal.xcodeproj"
echo ""
echo "2. In Project Navigator, select 'modal' PROJECT (blue icon at top)"
echo ""
echo "3. In the main editor, go to the 'Info' tab"
echo ""
echo "4. Under 'Configurations', expand both Debug and Release"
echo ""
echo "5. For each configuration:"
echo "   - Look for the 'modal' row (the target)"
echo "   - Click on it to reveal a dropdown"
echo "   - Select 'Config' from the dropdown"
echo ""
echo "6. Clean build folder: Product → Clean Build Folder (⇧⌘K)"
echo ""
echo "7. Rebuild and run"
echo ""

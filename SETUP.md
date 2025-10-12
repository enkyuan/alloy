# Modal Local Setup

## Structure
modal/
├── apps/
│   ├── ios/          # SwiftUI iOS app
│   └── api/          # FastAPI backend

## FastAPI Backend Setup

### 1. Navigate to API directory
cd apps/api

### 2. Install Poetry dependencies
poetry install

### 3. Add dependencies
poetry add fastapi uvicorn[standard] sqlalchemy alembic psycopg2-binary pydantic pydantic-settings python-jose[cryptography] passlib[bcrypt] asyncpg

### 4. Add dev dependencies
poetry add --group dev pytest pytest-asyncio pytest-cov httpx black ruff mypy

### 5. Set up environment
cp .env.example .env
# Edit .env with your database credentials

### 6. Run migrations
poetry run alembic upgrade head

### 7. Start development server
poetry run uvicorn app.main:app --reload

## iOS App Setup

### Prerequisites
- macOS with Xcode 15.0 or later
- iOS 17.0+ SDK
- Apple Developer account (for physical device testing)

### 1. Open Project in Xcode
```bash
open apps/ios/modal.xcodeproj
```

### 2. Configure the Project

#### Update API Endpoint
Before running, update the API endpoint in your iOS app configuration:
- Open `apps/ios/modal/Config.swift` (or wherever your API URL is configured)
- For simulator: `http://localhost:8000`
- For physical device: `http://<YOUR_LOCAL_IP>:8000` (e.g., `http://192.168.1.100:8000`)

To find your local IP:
```bash
ipconfig getifaddr en0  # For WiFi
ipconfig getifaddr en1  # For Ethernet
```

### 3. Running on iOS Simulator

#### Using Xcode GUI:
1. Select a simulator from the device dropdown (e.g., "iPhone 17 Pro")
   - Click on the device selector next to the scheme name in the toolbar
   - Choose any iPhone simulator running iOS 17.0+
2. Press `Cmd + R` or click the "Play" button to build and run

#### Using Command Line:
```bash
# List available simulators
xcrun simctl list devices available

# Boot a specific simulator (e.g., iPhone 17)
xcrun simctl boot "iPhone 17"

# Build and run on simulator
cd apps/modal && xcodebuild -project modal.xcodeproj -scheme modal -destination 'platform=iOS Simulator,name=iPhone 17' -configuration Debug build && xcrun simctl install "iPhone 17" ~/Library/Developer/Xcode/DerivedData/modal-*/Build/Products/Debug-iphonesimulator/modal.app && xcrun simctl launch "iPhone 17" com.app.modal

### 4. Running on Physical iPhone

#### Setup Code Signing:
1. In Xcode, select the project in the navigator
2. Select the "modal" target
3. Go to "Signing & Capabilities" tab
4. Check "Automatically manage signing"
5. Select your Team from the dropdown (requires Apple Developer account)
6. Xcode will automatically create a provisioning profile

#### Deploy to Device:
1. Connect your iPhone via USB or WiFi
2. Trust the computer on your iPhone when prompted
3. Select your iPhone from the device dropdown in Xcode
4. Press `Cmd + R` to build and run

#### Trust Developer Certificate (First Time):
If you see "Untrusted Developer" when launching:
1. On your iPhone: Settings → General → VPN & Device Management
2. Tap on your developer profile
3. Tap "Trust [Your Name]"
4. Launch the app again

### 5. Start the Backend API

The iOS app requires the FastAPI backend to be running:
```bash
cd apps/api
poetry run uvicorn app.main:app --reload --host 0.0.0.0
```

**Note:** Use `--host 0.0.0.0` to allow connections from physical devices on the same network.

### 6. Troubleshooting

#### Simulator can't connect to API:
- Ensure API is running on `http://localhost:8000`
- Check the API endpoint in your iOS app configuration
- Verify API is accessible: `curl http://localhost:8000/docs`

#### Physical device can't connect to API:
- Ensure both iPhone and computer are on the same WiFi network
- Use your local IP address (not localhost) in the API configuration
- Check firewall settings allow connections on port 8000
- Verify API is accessible from device: open `http://<YOUR_IP>:8000/docs` in Safari

#### Build errors:
- Clean build folder: `Cmd + Shift + K` or `Product → Clean Build Folder`
- Delete DerivedData: `rm -rf ~/Library/Developer/Xcode/DerivedData/`
- Update Xcode to the latest version

#### Code signing issues:
- Ensure you're logged into Xcode with your Apple ID: `Xcode → Settings → Accounts`
- Try manual signing if automatic fails
- Check that your Apple Developer account is in good standing

### 7. Running Tests

```bash
# Backend tests
cd apps/api
poetry run pytest

# iOS tests (using xcodebuild)
cd apps/ios
xcodebuild test \
  -project modal.xcodeproj \
  -scheme modal \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

### 8. Quick Start Commands

```bash
# Terminal 1: Start API
cd apps/api && poetry run uvicorn app.main:app --reload --host 0.0.0.0

# Terminal 2: Open iOS app
open apps/ios/modal.xcodeproj
# Then press Cmd + R in Xcode
```

# Google Sign-In Setup for iOS

## Step 1: Add Google Sign-In SDK to Xcode

1. Open your Xcode project
2. Go to **File** → **Add Package Dependencies**
3. Enter the URL: `https://github.com/google/GoogleSignIn-iOS`
4. Click **Add Package**
5. Select **GoogleSignIn** and **GoogleSignInSwift** libraries
6. Click **Add Package**

## Step 2: Configure Info.plist

Open `modal/Info.plist` and add the following:

### A. Add Google Client ID

Add a new key-value pair:
```xml
<key>GIDClientID</key>
<string>YOUR_IOS_CLIENT_ID.apps.googleusercontent.com</string>
```

**Replace** `YOUR_IOS_CLIENT_ID.apps.googleusercontent.com` with your actual iOS Client ID from Google Cloud Console.

### B. Add URL Scheme

Add URL Types to handle OAuth callback:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleTypeRole</key>
        <string>Editor</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>com.googleusercontent.apps.YOUR_IOS_CLIENT_ID</string>
        </array>
    </dict>
</array>
```

**Important**: Replace `YOUR_IOS_CLIENT_ID` with just the numeric/alphanumeric part of your client ID (without `.apps.googleusercontent.com`).

For example, if your client ID is:
```
123456789-abcdefg.apps.googleusercontent.com
```

Then your URL scheme should be:
```
com.googleusercontent.apps.123456789-abcdefg
```

### Complete Info.plist Example

Your Info.plist should look like this:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Existing keys -->
    <key>UIBackgroundModes</key>
    <array>
        <string>remote-notification</string>
    </array>
    
    <!-- Add Google Client ID -->
    <key>GIDClientID</key>
    <string>YOUR_IOS_CLIENT_ID.apps.googleusercontent.com</string>
    
    <!-- Add URL Schemes -->
    <key>CFBundleURLTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeRole</key>
            <string>Editor</string>
            <key>CFBundleURLSchemes</key>
            <array>
                <string>com.googleusercontent.apps.YOUR_IOS_CLIENT_ID</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
```

## Step 3: Update App Delegate (if needed)

In your `modalApp.swift`, add URL handling:

```swift
import SwiftUI
import SwiftData
import GoogleSignIn

@main
struct modalApp: App {
    var sharedModelContainer: ModelContainer = {
        let schema = Schema([
            Item.self,
        ])
        let modelConfiguration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)

        do {
            return try ModelContainer(for: schema, configurations: [modelConfiguration])
        } catch {
            fatalError("Could not create ModelContainer: \(error)")
        }
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onOpenURL { url in
                    GIDSignIn.sharedInstance.handle(url)
                }
        }
        .modelContainer(sharedModelContainer)
    }
}
```

## Step 4: Configure Backend API URL

In `Services/AuthenticationService.swift`, update the base URL to your backend:

```swift
init(baseURL: String = "http://YOUR_BACKEND_URL/api/v1") {
    self.baseURL = baseURL
    self.session = URLSession.shared
    super.init()
    loadSavedTokens()
}
```

For local development:
- **iOS Simulator**: `http://localhost:8000/api/v1`
- **Physical iPhone**: `http://YOUR_COMPUTER_IP:8000/api/v1` (e.g., `http://192.168.1.100:8000/api/v1`)

## Step 5: Test the Integration

1. **Start your backend**:
   ```bash
   cd apps/api
   poetry run uvicorn app.main:app --reload --host 0.0.0.0
   ```

2. **Run your iOS app** in Xcode

3. **Tap "Continue with Google"**

4. **Sign in with your Google account**

5. **Check the logs** for successful authentication:
   ```
   ✅ Successfully authenticated: your-email@gmail.com
   ```

## Troubleshooting

### "Unable to get root view controller"
- Make sure your app has a proper window hierarchy
- Try restarting the app

### "Google Sign-In failed"
- Check that GIDClientID in Info.plist matches your iOS Client ID
- Verify URL scheme is correctly formatted
- Check that the client ID is enabled in Google Cloud Console

### "Failed to get Google ID token"
- The sign-in may have been cancelled
- Try signing in again

### "Authentication failed: [error]"
- Check that your backend is running
- Verify the API base URL is correct
- Check backend logs for detailed error messages
- Ensure Supabase is configured with your Google OAuth credentials

### Backend Connection Issues

If testing on a physical device:
1. Find your computer's local IP: `ifconfig | grep inet`
2. Update the baseURL to use your IP instead of localhost
3. Make sure your iPhone and computer are on the same WiFi network
4. Update your backend CORS settings to allow your IP

## Next Steps

After successful Google authentication:

1. **Navigate to main app**: Update the TODO in `handleGoogleSignIn()` to navigate users to your main app screen
2. **Persist auth state**: The AuthenticationService already saves tokens to UserDefaults
3. **Handle token refresh**: Implement automatic token refresh before expiry
4. **Add sign out**: Implement sign out functionality
5. **Add Apple Sign In**: Follow similar pattern for Apple authentication

## Security Notes

- Never commit your Google Client ID to public repositories (use environment variables or config files)
- In production, use HTTPS for your backend API
- Implement proper error handling and logging
- Consider adding biometric authentication (Face ID/Touch ID) for additional security

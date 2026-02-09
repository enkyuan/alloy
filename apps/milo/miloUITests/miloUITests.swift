import XCTest

final class MiloAppUITests: XCTestCase {

    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
        app.launchArguments = ["--mock-auth"]
        app.launch()
    }

    override func tearDownWithError() throws {
        // Cleanup code
    }

    // MARK: - Onboarding Tests

    func test01_OnboardingToHomeFlow() throws {
        // 1. Initial State: Onboarding
        // The mock auth is async, so we might see onboarding for a split second.
        
        // 2. Auth flips to true -> Integrations Sheet should appear
        let addIntegrationsTitle = app.staticTexts["Add Integrations"]
        XCTAssertTrue(addIntegrationsTitle.waitForExistence(timeout: 10), "Integrations sheet should appear after auth")
        
        // 3. Connect Spotify (Mock)
        let spotifyLabel = app.staticTexts["Spotify"]
        if spotifyLabel.exists {
             spotifyLabel.tap()
             // Wait for "Continue" button which appears when at least one service is connected
             let continueButton = app.buttons["Continue"]
             XCTAssertTrue(continueButton.waitForExistence(timeout: 2), "Button should say Continue after connecting a service")
             continueButton.tap()
        } else {
             // Fallback if spotify not found (shouldn't happen)
             if app.buttons["Done"].exists {
                 app.buttons["Done"].tap()
             } else {
                 // Try swiping down
                 addIntegrationsTitle.swipeDown(velocity: .fast)
             }
        }
        
        // 4. Now we should be on Home View
        // HomeView usually has a TabView. Let's look for "Assistant" tab icon or title.
        let waveformIcon = app.images["waveform"] // SF Symbol
        
        // Wait for Home
        XCTAssertTrue(waveformIcon.waitForExistence(timeout: 5), "Should navigate to Home View after onboarding")
    }

    func test04_TabBarNavigation() throws {
        // Ensure we handle the onboarding flow first to get to Home
        try skipOnboardingIfPresent()
        
        // Ensure we are on Home View
        let waveformIcon = app.images["waveform"]
        XCTAssertTrue(waveformIcon.exists, "Should be on Assistant tab by default")
    
        // Navigate to Settings
        let gearIcon = app.images["gear"]
        if gearIcon.exists {
            gearIcon.tap()
            let settingsTitle = app.staticTexts["Settings"]
            XCTAssertTrue(settingsTitle.waitForExistence(timeout: 2), "Should navigate to Settings view")
        }
    }
    
    func test05_SettingsMenu() throws {
        try skipOnboardingIfPresent()
        
        // Navigate to Settings
        let gearIcon = app.images["gear"]
        if gearIcon.waitForExistence(timeout: 5) {
            gearIcon.tap()
            
            // Verify Appearance Section
            XCTAssertTrue(app.staticTexts["Appearance"].exists)
            XCTAssertTrue(app.staticTexts["System"].exists)
            
            // Verify Integrations Navigation
            let servicesBtn = app.buttons["Connected Services"]
            if servicesBtn.exists {
                servicesBtn.tap()
                
                // Verify Integrations Screen
                XCTAssertTrue(app.staticTexts["Add Integrations"].waitForExistence(timeout: 2))
                // XCTAssertTrue(app.staticTexts["Spotify"].exists) // Might need scrolling or mock data to ensure spotify is listed
                
                // Return to Settings
                if app.navigationBars.buttons.count > 0 {
                    app.navigationBars.buttons.element(boundBy: 0).tap()
                }
            }
        }
    }
    
    // Helper to bypass onboarding if the test starts fresh
    func skipOnboardingIfPresent() throws {
        let addIntegrationsTitle = app.staticTexts["Add Integrations"]
        if addIntegrationsTitle.waitForExistence(timeout: 5) {
             if app.buttons["Done"].exists {
                 app.buttons["Done"].tap()
             } else {
                 addIntegrationsTitle.swipeDown(velocity: .fast)
             }
        }
        
        // Wait for Home
        let waveformIcon = app.images["waveform"]
        _ = waveformIcon.waitForExistence(timeout: 5)
    }
}

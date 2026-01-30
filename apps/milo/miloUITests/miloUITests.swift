import XCTest

final class MiloAppUITests: XCTestCase {

    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
        // In the future, pass launch arguments here to mock authentication if supported
        // app.launchArguments = ["--mock-auth"]
        app.launch()
    }

    override func tearDownWithError() throws {
        // Cleanup code
    }

    // MARK: - Onboarding Tests

    func test01_OnboardingUIStructure() throws {
        // Verify the static greeting "Hey Milo," appears.
        // It animates in, so we wait.
        let greeting = app.staticTexts["Hey Milo,"]
        XCTAssertTrue(
            greeting.waitForExistence(timeout: 5), "Initial greeting 'Hey Milo,' should appear.")

        // Verify the main Title and Subtitle at the bottom
        let mainTitle = app.staticTexts["Meet Milo"]
        XCTAssertTrue(
            mainTitle.waitForExistence(timeout: 2), "Title 'Meet Milo' should be visible.")

        let subtitle = app.staticTexts["Your agentic voice assistant"]
        XCTAssertTrue(subtitle.exists, "Subtitle should be visible.")
    }

    func test02_OnboardingCarousel() throws {
        // Verify that dynamic phrases cycle through in the preview card
        let phrases = [
            "Order Pad Thai from DoorDash",
            "Play Midnight City on Apple Music",
            "Get me some paper towels on Instacart",
        ]

        // Predicate to find any static text element that matches one of the phrases
        let predicate = NSPredicate(format: "label IN %@", phrases)
        let carouselLabel = app.staticTexts.element(matching: predicate)

        // Wait for animation to cycle to at least one phrase
        XCTAssertTrue(
            carouselLabel.waitForExistence(timeout: 10),
            "One of the carousel phrases should appear.")
    }

    func test03_AuthenticationOptions() throws {
        // Verify all three authentication buttons are present
        let appleBtn = app.buttons["Continue with Apple"]
        let googleBtn = app.buttons["Continue with Google"]
        let emailBtn = app.buttons["Continue with Email"]

        XCTAssertTrue(appleBtn.exists, "Apple Sign In button missing")
        XCTAssertTrue(googleBtn.exists, "Google Sign In button missing")
        XCTAssertTrue(emailBtn.exists, "Email Sign In button missing")

        // Verify interaction (simple tap check)
        // Note: We cannot fully test the system auth flow in simulation easily, but we can verify touchability
        XCTAssertTrue(emailBtn.isHittable, "Email button should be tappable")
    }

    // MARK: - Post-Auth Tests (Placeholder)

    /*
    The following tests cover the Home/Assistant and Settings views.
    These are commented out because they require an authenticated state.
    To enable them, the app needs a Mock Authentication mode (e.g. via launch arguments)
    that bypasses OnboardingView and loads HomeView with a dummy user.
    */

    /*
    func test04_TabBarNavigation() throws {
        // Ensure we are on Home View
        let waveformIcon = app.images["WaveformIcon"] // Or whatever accessibility identifier we set
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
        // Navigate to Settings
        let gearIcon = app.images["gear"]
        gearIcon.tap()
    
        // Verify Appearance Section
        XCTAssertTrue(app.staticTexts["Appearance"].exists)
        XCTAssertTrue(app.staticTexts["System"].exists)
        XCTAssertTrue(app.staticTexts["Light"].exists)
    
        // Verify Integrations Navigation
        let servicesBtn = app.buttons["Connected Services"]
        XCTAssertTrue(servicesBtn.exists)
        servicesBtn.tap()
    
        // Verify Integrations Screen
        XCTAssertTrue(app.staticTexts["Add Integrations"].waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["Spotify"].exists)
    
        // Return to Settings
        app.navigationBars.buttons.element(boundBy: 0).tap() // Back button
    }
    
    func test06_AssistantInteraction() throws {
        // Return to Assistant Tab
        let waveformIcon = app.images["waveform"] // Assuming SF Symbol name or asset
        waveformIcon.tap()
    
        // Check Mic Button
        let micButton = app.buttons["mic.fill"]
        XCTAssertTrue(micButton.exists)
    
        // Test Recording (Mock) - requires app to handle mock recording
        // micButton.tap()
        // XCTAssertTrue(app.staticTexts["Listening..."].exists)
    }
    */
}

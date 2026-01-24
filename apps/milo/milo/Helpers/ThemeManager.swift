import Combine
import SwiftUI

enum AppTheme: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

@MainActor
class ThemeManager: ObservableObject {
    @Published var currentTheme: AppTheme {
        didSet {
            UserDefaults.standard.set(currentTheme.rawValue, forKey: "selectedTheme")
        }
    }

    static let shared = ThemeManager()

    private init() {
        if let storedTheme = UserDefaults.standard.string(forKey: "selectedTheme"),
            let theme = AppTheme(rawValue: storedTheme)
        {
            self.currentTheme = theme
        } else {
            self.currentTheme = .system
        }
    }
}

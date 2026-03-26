
import Foundation

enum Environment {

    nonisolated(unsafe) static var apiBaseURL: String {
        guard let urlString = Bundle.main.infoDictionary?["API_BASE_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("API_BASE_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }

    nonisolated(unsafe) static var websocketURL: String {
        guard let urlString = Bundle.main.infoDictionary?["WEBSOCKET_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("WEBSOCKET_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }

    nonisolated(unsafe) static var supabaseURL: String {
        guard let urlString = Bundle.main.infoDictionary?["SUPABASE_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("SUPABASE_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }

    nonisolated(unsafe) static var supabaseAnonKey: String {
        guard let key = Bundle.main.infoDictionary?["SUPABASE_ANON_KEY"] as? String,
              !key.isEmpty else {
            fatalError("SUPABASE_ANON_KEY not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return key
    }

    nonisolated(unsafe) static var isDebugLoggingEnabled: Bool {
        if let enabled = Bundle.main.infoDictionary?["DEBUG_LOGGING"] as? String {
            return enabled.uppercased() == "YES" || enabled.lowercased() == "true"
        }
        #if DEBUG
        return true
        #else
        return false
        #endif
    }


    nonisolated static func value(for key: String) -> String? {
        Bundle.main.infoDictionary?[key] as? String
    }
}

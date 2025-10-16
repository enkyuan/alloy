//
//  Environment.swift
//  modal
//
//  Environment configuration manager
//  Reads from Info.plist (populated from Config.xcconfig at build time)
//

import Foundation

/// Environment configuration manager
enum Environment {
    // MARK: - Environment Values
    
    /// Backend API base URL
    nonisolated(unsafe) static var apiBaseURL: String {
        guard let urlString = Bundle.main.infoDictionary?["API_BASE_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("API_BASE_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }
    
    /// WebSocket URL
    nonisolated(unsafe) static var websocketURL: String {
        guard let urlString = Bundle.main.infoDictionary?["WEBSOCKET_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("WEBSOCKET_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }
    
    /// Supabase URL
    nonisolated(unsafe) static var supabaseURL: String {
        guard let urlString = Bundle.main.infoDictionary?["SUPABASE_URL"] as? String,
              !urlString.isEmpty else {
            fatalError("SUPABASE_URL not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return urlString
    }
    
    /// Supabase anon key
    nonisolated(unsafe) static var supabaseAnonKey: String {
        guard let key = Bundle.main.infoDictionary?["SUPABASE_ANON_KEY"] as? String,
              !key.isEmpty else {
            fatalError("SUPABASE_ANON_KEY not found in Info.plist. Make sure Config.xcconfig is set up correctly.")
        }
        return key
    }
    
    /// Enable debug logging
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
    
    // MARK: - Helper Methods
    
    /// Get custom environment variable from Info.plist
    nonisolated static func value(for key: String) -> String? {
        Bundle.main.infoDictionary?[key] as? String
    }
}

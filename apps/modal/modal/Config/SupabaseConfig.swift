import Foundation
import Supabase

/// Supabase configuration and client initialization
/// Reference: https://supabase.com/docs/reference/swift/initializing
enum SupabaseConfig {
    // MARK: - Configuration
    
    /// Supabase project URL (from Environment config)
    static let supabaseURL = URL(string: Environment.supabaseURL)!
    
    /// Supabase anon/public key (from Environment config)
    /// Note: This key is safe to expose in client applications.
    /// It only allows operations permitted by your Row Level Security policies.
    /// Reference: https://supabase.com/docs/guides/api/api-keys
    static let supabaseAnonKey = Environment.supabaseAnonKey
    
    // MARK: - Shared Client
    
    /// Shared Supabase client instance
    /// Use this throughout your app for all Supabase operations
    /// Example: SupabaseConfig.shared.auth.signIn(...)
    /// 
    /// Note: Using Google Sign-In SDK directly, so no OAuth redirect URL needed
    static let shared = SupabaseClient(
        supabaseURL: supabaseURL,
        supabaseKey: supabaseAnonKey
    )
}


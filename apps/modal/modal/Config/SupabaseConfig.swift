import Foundation
import Supabase

/// Supabase configuration and client initialization
/// Reference: https://supabase.com/docs/reference/swift/initializing
enum SupabaseConfig {
    // MARK: - Configuration
    
    /// Supabase project URL
    /// For local development: http://localhost:8001
    /// For production: https://your-project.supabase.co
    static let supabaseURL = URL(string: "http://localhost:8001")!
    
    /// Supabase anon/public key
    /// Note: This key is safe to expose in client applications.
    /// It only allows operations permitted by your Row Level Security policies.
    /// Reference: https://supabase.com/docs/guides/api/api-keys
    static let supabaseAnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJvbGUiOiJhbm9uIiwiaWF0IjoxNzYwMzI4ODk4LCJleHAiOjQxMDI0NDQ4MDB9.zc_DOTFuH0bbMzTvjp5YzE34hEQnHCvdp6nlHAOwpuA"
    
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


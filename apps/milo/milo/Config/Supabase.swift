<<<<<<< HEAD:apps/modal/modal/Config/Supabase.swift
import Foundation
import Supabase

let supabase = SupabaseClient(
    supabaseURL: URL(string: Environment.supabaseURL)!,
    supabaseKey: Environment.supabaseAnonKey
)
=======
import Auth
import Foundation
import Supabase

let supabase: SupabaseClient = {
    let urlString = Environment.supabaseURL
    let anonKey = Environment.supabaseAnonKey

    print("Initializing Supabase client...")
    print("Supabase URL: \(urlString)")
    print("Anon Key length: \(anonKey.count) characters")

    guard let url = URL(string: urlString) else {
        fatalError(
            "Invalid Supabase URL: '\(urlString)'. Check Config.xcconfig and ensure URLs are properly formatted (e.g., http:/$()/localhost:8000)"
        )
    }

    guard !anonKey.isEmpty else {
        fatalError("Supabase anon key is empty. Check Config.xcconfig")
    }

    let client = SupabaseClient(
        supabaseURL: url,
        supabaseKey: anonKey,
        options: SupabaseClientOptions(
            auth: .init(emitLocalSessionAsInitialSession: true)
        )
    )

    print("Supabase client initialized successfully")
    return client
}()
>>>>>>> codex/refactor:apps/milo/milo/Config/Supabase.swift

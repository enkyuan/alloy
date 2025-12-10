import Foundation
import Supabase

let supabase = SupabaseClient(
    supabaseURL: URL(string: Environment.supabaseURL)!,
    supabaseKey: Environment.supabaseAnonKey
)

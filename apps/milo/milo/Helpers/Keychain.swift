import Foundation
import Security

/// Helper class for securely storing data in the iOS Keychain
class Keychain {

    /// Save a string value to the keychain
    static func save(key: String, value: String) {
        guard let data = value.data(using: .utf8) else { return }

        // Check if item already exists
        if load(key: key) != nil {
            // Update existing item
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrAccount as String: key,
            ]

            let attributes: [String: Any] = [
                kSecValueData as String: data
            ]

            SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        } else {
            // Add new item
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrAccount as String: key,
                kSecValueData as String: data,
            ]

            SecItemAdd(query as CFDictionary, nil)
        }
    }

    /// Load a string value from the keychain
    static func load(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
            let data = result as? Data,
            let value = String(data: data, encoding: .utf8)
        else {
            return nil
        }

        return value
    }

    /// Delete a value from the keychain
    static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]

        SecItemDelete(query as CFDictionary)
    }
}

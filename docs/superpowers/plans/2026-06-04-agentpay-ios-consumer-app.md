# agentpay iOS Consumer App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Swift/SwiftUI iOS app with three screens: wallet (Stripe Payment Element), transactions (paginated list), and activity (plain-language feed). Auth is email/password against the consumer service.

**Architecture:** Single-target SwiftUI app. Networking is a thin `APIClient` struct using `URLSession` + `async/await`. JWT is stored in Keychain via the Security framework. Stripe iOS SDK handles all card UI. No third-party networking library — URLSession is sufficient and keeps the dependency tree minimal.

**Tech Stack:** Swift 5.10+, SwiftUI, Xcode 16+, Stripe iOS SDK (`StripePaymentSheet`), Security framework (Keychain), `URLSession`.

**Dependency:** Requires Plan 2 (consumer service) running — app talks to `apps/consumer` on port 8091.

---

## File Map

| file | action | responsibility |
|------|--------|---------------|
| `apps/ios/AgentPay.xcodeproj` | create | Xcode project |
| `apps/ios/AgentPay/AgentPayApp.swift` | create | app entry point + root navigation |
| `apps/ios/AgentPay/Networking/APIClient.swift` | create | typed HTTP client for consumer service |
| `apps/ios/AgentPay/Networking/Models.swift` | create | Codable response types |
| `apps/ios/AgentPay/Auth/AuthViewModel.swift` | create | login/signup state + Keychain token storage |
| `apps/ios/AgentPay/Auth/LoginView.swift` | create | email + password form |
| `apps/ios/AgentPay/Auth/SignupView.swift` | create | account creation form |
| `apps/ios/AgentPay/Wallet/WalletViewModel.swift` | create | wallet status + SetupIntent fetch |
| `apps/ios/AgentPay/Wallet/WalletView.swift` | create | wallet screen with Stripe Payment Element |
| `apps/ios/AgentPay/Transactions/TransactionViewModel.swift` | create | paginated transaction list |
| `apps/ios/AgentPay/Transactions/TransactionsView.swift` | create | transactions list screen |
| `apps/ios/AgentPay/Activity/ActivityViewModel.swift` | create | activity feed list |
| `apps/ios/AgentPay/Activity/ActivityView.swift` | create | plain-language feed screen |

---

## Task 1: Xcode project scaffold

- [ ] **Step 1: Create the Xcode project**

In Xcode: File > New > Project > iOS > App
- Product Name: `AgentPay`
- Bundle Identifier: `dev.agentpay.consumer`
- Interface: SwiftUI
- Language: Swift
- Save to: `apps/ios/`

- [ ] **Step 2: Add Stripe iOS SDK via Swift Package Manager**

In Xcode: File > Add Package Dependencies
- URL: `https://github.com/stripe/stripe-ios`
- Version: Up to Next Major from `23.0.0`
- Select: `StripePaymentSheet`

- [ ] **Step 3: Add a Config.plist for environment**

Create `apps/ios/AgentPay/Config.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ConsumerAPIBaseURL</key>
    <string>http://localhost:8091</string>
    <key>StripePublishableKey</key>
    <string>pk_test_REPLACE_ME</string>
</dict>
</plist>
```

- [ ] **Step 4: Commit the scaffold**

```bash
git add apps/ios/
git commit -m "feat(ios): scaffold Xcode project + Stripe SDK"
```

---

## Task 2: Networking layer

**Files:**
- Create: `apps/ios/AgentPay/Networking/Models.swift`
- Create: `apps/ios/AgentPay/Networking/APIClient.swift`

- [ ] **Step 1: Write Models.swift**

Create `apps/ios/AgentPay/Networking/Models.swift`:

```swift
import Foundation

// MARK: - Auth

struct AuthResponse: Decodable {
    let token: String
    let consumer: ConsumerProfile
}

struct ConsumerProfile: Decodable {
    let id: String
    let email: String
    let stripeCustomerId: String?

    enum CodingKeys: String, CodingKey {
        case id, email
        case stripeCustomerId = "stripe_customer_id"
    }
}

// MARK: - Wallet

struct WalletStatus: Decodable {
    let stripeCustomerId: String?
    let paymentMethods: [PaymentMethodSummary]

    enum CodingKeys: String, CodingKey {
        case stripeCustomerId = "stripe_customer_id"
        case paymentMethods = "payment_methods"
    }
}

struct PaymentMethodSummary: Decodable, Identifiable {
    let id: String
    let brand: String
    let last4: String
}

struct SetupIntentResponse: Decodable {
    let clientSecret: String

    enum CodingKeys: String, CodingKey {
        case clientSecret = "client_secret"
    }
}

// MARK: - Transactions

struct Transaction: Decodable, Identifiable {
    let id: String
    let amountCents: Int
    let currency: String
    let status: String
    let plainLabel: String
    let merchantId: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, currency, status
        case amountCents = "amount_cents"
        case plainLabel = "plain_label"
        case merchantId = "merchant_id"
        case createdAt = "created_at"
    }

    var formattedAmount: String {
        let dollars = Double(amountCents) / 100.0
        return String(format: "$%.2f", dollars)
    }
}

// MARK: - Activity

struct ActivityEntry: Decodable, Identifiable {
    let id: String
    let label: String
    let status: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, label, status
        case createdAt = "created_at"
    }
}

// MARK: - Errors

struct APIError: Decodable, Error {
    let error: String
}
```

- [ ] **Step 2: Write APIClient.swift**

Create `apps/ios/AgentPay/Networking/APIClient.swift`:

```swift
import Foundation

final class APIClient {
    private let baseURL: URL
    private var token: String?

    init(baseURL: URL, token: String? = nil) {
        self.baseURL = baseURL
        self.token = token
    }

    func setToken(_ token: String) {
        self.token = token
    }

    // MARK: - Auth

    func signup(email: String, password: String) async throws -> AuthResponse {
        return try await post("/v1/auth/signup", body: ["email": email, "password": password])
    }

    func login(email: String, password: String) async throws -> AuthResponse {
        return try await post("/v1/auth/login", body: ["email": email, "password": password])
    }

    // MARK: - Wallet

    func walletStatus() async throws -> WalletStatus {
        return try await get("/v1/wallet")
    }

    func walletSetup() async throws -> SetupIntentResponse {
        return try await post("/v1/wallet/setup", body: [:] as [String: String])
    }

    // MARK: - Transactions

    func transactions(limit: Int = 20, offset: Int = 0) async throws -> [Transaction] {
        return try await get("/v1/transactions?limit=\(limit)&offset=\(offset)")
    }

    // MARK: - Activity

    func activity(limit: Int = 20, offset: Int = 0) async throws -> [ActivityEntry] {
        return try await get("/v1/activity?limit=\(limit)&offset=\(offset)")
    }

    // MARK: - Internals

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "GET"
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return try await perform(request)
    }

    private func post<Body: Encodable, Response: Decodable>(_ path: String, body: Body) async throws -> Response {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONEncoder().encode(body)
        return try await perform(request)
    }

    private func perform<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        if !(200..<300).contains(http.statusCode) {
            let apiError = try? JSONDecoder().decode(APIError.self, from: data)
            throw apiError ?? APIError(error: "HTTP \(http.statusCode)")
        }
        let decoder = JSONDecoder()
        return try decoder.decode(T.self, from: data)
    }
}
```

- [ ] **Step 3: Build (Cmd+B)**

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/ios/AgentPay/Networking/
git commit -m "feat(ios): networking layer — APIClient + Codable models"
```

---

## Task 3: Keychain helper + Auth state

**Files:**
- Create: `apps/ios/AgentPay/Auth/AuthViewModel.swift`

- [ ] **Step 1: Write AuthViewModel.swift**

Create `apps/ios/AgentPay/Auth/AuthViewModel.swift`:

```swift
import Foundation
import Security

@MainActor
final class AuthViewModel: ObservableObject {
    @Published var isAuthenticated = false
    @Published var isLoading = false
    @Published var errorMessage: String?

    let api: APIClient

    private static let tokenKey = "agentpay.consumer.token"

    init(api: APIClient) {
        self.api = api
        if let saved = KeychainHelper.read(key: Self.tokenKey) {
            api.setToken(saved)
            isAuthenticated = true
        }
    }

    func signup(email: String, password: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await api.signup(email: email, password: password)
            persist(token: response.token)
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func login(email: String, password: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await api.login(email: email, password: password)
            persist(token: response.token)
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func logout() {
        KeychainHelper.delete(key: Self.tokenKey)
        api.setToken("")
        isAuthenticated = false
    }

    private func persist(token: String) {
        KeychainHelper.save(key: Self.tokenKey, value: token)
        api.setToken(token)
        isAuthenticated = true
    }
}

// MARK: - Keychain

enum KeychainHelper {
    static func save(key: String, value: String) {
        let data = Data(value.utf8)
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrAccount: key,
            kSecValueData: data,
        ]
        SecItemDelete(query as CFDictionary)
        SecItemAdd(query as CFDictionary, nil)
    }

    static func read(key: String) -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrAccount: key,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        SecItemCopyMatching(query as CFDictionary, &result)
        guard let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(key: String) {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrAccount: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
```

- [ ] **Step 2: Build (Cmd+B)**

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/ios/AgentPay/Auth/AuthViewModel.swift
git commit -m "feat(ios): AuthViewModel + Keychain token storage"
```

---

## Task 4: Auth screens

**Files:**
- Create: `apps/ios/AgentPay/Auth/LoginView.swift`
- Create: `apps/ios/AgentPay/Auth/SignupView.swift`

- [ ] **Step 1: Write LoginView.swift**

Create `apps/ios/AgentPay/Auth/LoginView.swift`:

```swift
import SwiftUI

struct LoginView: View {
    @ObservedObject var auth: AuthViewModel
    @State private var email = ""
    @State private var password = ""
    @State private var showSignup = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("agentpay")
                    .font(.largeTitle.bold())
                    .padding(.bottom, 20)

                TextField("Email", text: $email)
                    .keyboardType(.emailAddress)
                    .autocapitalization(.none)
                    .textFieldStyle(.roundedBorder)

                SecureField("Password", text: $password)
                    .textFieldStyle(.roundedBorder)

                if let error = auth.errorMessage {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                }

                Button {
                    Task { await auth.login(email: email, password: password) }
                } label: {
                    if auth.isLoading {
                        ProgressView()
                    } else {
                        Text("Sign In").frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(auth.isLoading || email.isEmpty || password.isEmpty)

                Button("Create account") { showSignup = true }
                    .font(.subheadline)
            }
            .padding()
            .sheet(isPresented: $showSignup) {
                SignupView(auth: auth)
            }
        }
    }
}
```

- [ ] **Step 2: Write SignupView.swift**

Create `apps/ios/AgentPay/Auth/SignupView.swift`:

```swift
import SwiftUI

struct SignupView: View {
    @ObservedObject var auth: AuthViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var email = ""
    @State private var password = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .autocapitalization(.none)
                    SecureField("Password", text: $password)
                }
                if let error = auth.errorMessage {
                    Section {
                        Text(error).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("Create Account")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Sign Up") {
                        Task {
                            await auth.signup(email: email, password: password)
                            if auth.isAuthenticated { dismiss() }
                        }
                    }
                    .disabled(auth.isLoading || email.isEmpty || password.isEmpty)
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}
```

- [ ] **Step 3: Build (Cmd+B)**

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/ios/AgentPay/Auth/
git commit -m "feat(ios): login + signup screens"
```

---

## Task 5: Wallet screen

**Files:**
- Create: `apps/ios/AgentPay/Wallet/WalletViewModel.swift`
- Create: `apps/ios/AgentPay/Wallet/WalletView.swift`

- [ ] **Step 1: Write WalletViewModel.swift**

Create `apps/ios/AgentPay/Wallet/WalletViewModel.swift`:

```swift
import Foundation
import StripePaymentSheet

@MainActor
final class WalletViewModel: ObservableObject {
    @Published var walletStatus: WalletStatus?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var paymentSheet: PaymentSheet?
    @Published var paymentResult: PaymentSheetResult?

    private let api: APIClient
    private let stripePublishableKey: String

    init(api: APIClient, stripePublishableKey: String) {
        self.api = api
        self.stripePublishableKey = stripePublishableKey
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            walletStatus = try await api.walletStatus()
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func prepareSetup() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await api.walletSetup()
            StripeAPI.defaultPublishableKey = stripePublishableKey
            var config = PaymentSheet.Configuration()
            config.merchantDisplayName = "agentpay"
            paymentSheet = PaymentSheet(setupIntentClientSecret: response.clientSecret, configuration: config)
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func handlePaymentResult(_ result: PaymentSheetResult) {
        paymentResult = result
        if case .completed = result {
            Task { await load() }
        }
    }
}
```

- [ ] **Step 2: Write WalletView.swift**

Create `apps/ios/AgentPay/Wallet/WalletView.swift`:

```swift
import SwiftUI
import StripePaymentSheet

struct WalletView: View {
    @StateObject private var vm: WalletViewModel

    init(api: APIClient, stripePublishableKey: String) {
        _vm = StateObject(wrappedValue: WalletViewModel(api: api, stripePublishableKey: stripePublishableKey))
    }

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading {
                    ProgressView()
                } else {
                    content
                }
            }
            .navigationTitle("Wallet")
            .task { await vm.load() }
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Add Card") { Task { await vm.prepareSetup() } }
                }
            }
            .paymentSheet(
                isPresented: Binding(
                    get: { vm.paymentSheet != nil },
                    set: { if !$0 { vm.paymentSheet = nil } }
                ),
                paymentSheet: vm.paymentSheet ?? PaymentSheet(setupIntentClientSecret: "", configuration: .init()),
                onCompletion: vm.handlePaymentResult
            )
        }
    }

    @ViewBuilder
    private var content: some View {
        if let status = vm.walletStatus, !status.paymentMethods.isEmpty {
            List(status.paymentMethods) { pm in
                HStack {
                    Image(systemName: "creditcard")
                    Text("\(pm.brand.capitalized) ••••\(pm.last4)")
                    Spacer()
                }
            }
        } else {
            VStack(spacing: 16) {
                Image(systemName: "wallet.pass")
                    .font(.system(size: 48))
                    .foregroundStyle(.secondary)
                Text("No payment methods saved")
                    .foregroundStyle(.secondary)
                Button("Add a card") { Task { await vm.prepareSetup() } }
                    .buttonStyle(.borderedProminent)
            }
        }
    }
}
```

- [ ] **Step 3: Build (Cmd+B)**

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/ios/AgentPay/Wallet/
git commit -m "feat(ios): wallet screen with Stripe Payment Element"
```

---

## Task 6: Transactions + Activity screens

**Files:**
- Create: `apps/ios/AgentPay/Transactions/TransactionViewModel.swift`
- Create: `apps/ios/AgentPay/Transactions/TransactionsView.swift`
- Create: `apps/ios/AgentPay/Activity/ActivityViewModel.swift`
- Create: `apps/ios/AgentPay/Activity/ActivityView.swift`

- [ ] **Step 1: Write TransactionViewModel.swift**

Create `apps/ios/AgentPay/Transactions/TransactionViewModel.swift`:

```swift
import Foundation

@MainActor
final class TransactionViewModel: ObservableObject {
    @Published var transactions: [Transaction] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            transactions = try await api.transactions()
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
```

- [ ] **Step 2: Write TransactionsView.swift**

Create `apps/ios/AgentPay/Transactions/TransactionsView.swift`:

```swift
import SwiftUI

struct TransactionsView: View {
    @StateObject private var vm: TransactionViewModel

    init(api: APIClient) {
        _vm = StateObject(wrappedValue: TransactionViewModel(api: api))
    }

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading {
                    ProgressView()
                } else if vm.transactions.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "list.bullet.rectangle")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("No transactions yet")
                            .foregroundStyle(.secondary)
                    }
                } else {
                    List(vm.transactions) { tx in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(tx.plainLabel)
                                    .font(.subheadline)
                                Text(tx.createdAt)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 4) {
                                Text(tx.formattedAmount)
                                    .font(.subheadline.bold())
                                statusBadge(tx.status)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("Transactions")
            .task { await vm.load() }
            .refreshable { await vm.load() }
        }
    }

    @ViewBuilder
    private func statusBadge(_ status: String) -> some View {
        Text(status)
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(statusColor(status).opacity(0.15))
            .foregroundStyle(statusColor(status))
            .clipShape(Capsule())
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "completed": return .green
        case "failed": return .red
        default: return .orange
        }
    }
}
```

- [ ] **Step 3: Write ActivityViewModel.swift**

Create `apps/ios/AgentPay/Activity/ActivityViewModel.swift`:

```swift
import Foundation

@MainActor
final class ActivityViewModel: ObservableObject {
    @Published var entries: [ActivityEntry] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api: APIClient

    init(api: APIClient) {
        self.api = api
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            entries = try await api.activity()
        } catch let e as APIError {
            errorMessage = e.error
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
```

- [ ] **Step 4: Write ActivityView.swift**

Create `apps/ios/AgentPay/Activity/ActivityView.swift`:

```swift
import SwiftUI

struct ActivityView: View {
    @StateObject private var vm: ActivityViewModel

    init(api: APIClient) {
        _vm = StateObject(wrappedValue: ActivityViewModel(api: api))
    }

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading {
                    ProgressView()
                } else if vm.entries.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "clock.arrow.circlepath")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("No activity yet")
                            .foregroundStyle(.secondary)
                        Text("When an agent takes an action on your behalf, it will appear here.")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                    }
                } else {
                    List(vm.entries) { entry in
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: iconName(entry.status))
                                .foregroundStyle(statusColor(entry.status))
                                .frame(width: 24)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.label)
                                    .font(.subheadline)
                                Text(entry.createdAt)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("Activity")
            .task { await vm.load() }
            .refreshable { await vm.load() }
        }
    }

    private func iconName(_ status: String) -> String {
        switch status {
        case "completed": return "checkmark.circle.fill"
        case "failed": return "xmark.circle.fill"
        default: return "clock.fill"
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "completed": return .green
        case "failed": return .red
        default: return .orange
        }
    }
}
```

- [ ] **Step 5: Build (Cmd+B)**

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/ios/AgentPay/Transactions/ apps/ios/AgentPay/Activity/
git commit -m "feat(ios): transactions + activity screens"
```

---

## Task 7: Root navigation + app entry point

**Files:**
- Modify: `apps/ios/AgentPay/AgentPayApp.swift`

- [ ] **Step 1: Write AgentPayApp.swift**

Replace the contents of `apps/ios/AgentPay/AgentPayApp.swift`:

```swift
import SwiftUI

@main
struct AgentPayApp: App {
    private let api: APIClient
    private let stripeKey: String
    @StateObject private var auth: AuthViewModel

    init() {
        // Load config from Config.plist
        let config = Bundle.main.infoDictionary
        let baseURLString = (config?["ConsumerAPIBaseURL"] as? String) ?? "http://localhost:8091"
        let publishableKey = (config?["StripePublishableKey"] as? String) ?? ""

        let apiClient = APIClient(baseURL: URL(string: baseURLString)!)
        self.api = apiClient
        self.stripeKey = publishableKey
        _auth = StateObject(wrappedValue: AuthViewModel(api: apiClient))
    }

    var body: some Scene {
        WindowGroup {
            if auth.isAuthenticated {
                TabView {
                    WalletView(api: api, stripePublishableKey: stripeKey)
                        .tabItem { Label("Wallet", systemImage: "creditcard") }
                    TransactionsView(api: api)
                        .tabItem { Label("Transactions", systemImage: "list.bullet") }
                    ActivityView(api: api)
                        .tabItem { Label("Activity", systemImage: "clock.arrow.circlepath") }
                }
            } else {
                LoginView(auth: auth)
            }
        }
    }
}
```

- [ ] **Step 2: Build and run in simulator (Cmd+R)**

Select any iPhone simulator. Expected: app launches, shows Login screen.

- [ ] **Step 3: Smoke test auth flow in simulator**

1. Tap "Create account" — SignupView appears
2. Enter email + password, tap Sign Up
3. Expect: main tab view appears with Wallet, Transactions, Activity tabs
4. Wallet tab shows "No payment methods saved"
5. Activity tab shows "No activity yet"

- [ ] **Step 4: Commit**

```bash
git add apps/ios/AgentPay/AgentPayApp.swift
git commit -m "feat(ios): root navigation — tab view + auth gate"
```

---

## Task 8: Add to workspace and final build

- [ ] **Step 1: Add ios to turbo workspace (if using turbo)**

In `turbo.json`, verify the `apps/ios` path is excluded (Xcode projects don't participate in turbo pipelines). No changes needed — turbo only picks up `package.json` workspaces.

- [ ] **Step 2: Final clean build**

In Xcode: Product > Clean Build Folder (Shift+Cmd+K), then Cmd+B.

Expected: 0 errors, 0 warnings related to agentpay code.

- [ ] **Step 3: Final commit**

```bash
git add apps/ios/
git commit -m "feat(ios): complete consumer app — wallet, transactions, activity"
```

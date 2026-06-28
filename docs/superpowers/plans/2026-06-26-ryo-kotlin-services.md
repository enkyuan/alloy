# ryo Kotlin Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `ryo/ledger/` and `ryo/events/` as Kotlin services beside the existing Go services. Sequenced ledger-first so customer-visible value lands before infrastructure churn.

**Architecture:** Three services share one Postgres. The Kotlin services read existing tables; each writes exactly one new table it owns. Framework / library / concurrency choices belong to the implementer — this plan locks behavior, schema, and parity, not stack.

**Tech Stack:** Kotlin on JVM 21. Anything else (HTTP framework, DB driver, test harness, build tool) is the implementer's call as long as the contract and parity tests pass.

## Global Constraints

- JVM 21 baseline. No GraalVM native-image (out of scope).
- Kotlin only. No other JVM languages.
- New services live under `ryo/events/` and `ryo/ledger/`. Migrations go in `ryo/api/migrations/` because the schema is shared.
- Webhook signing format is fixed: `X-Ryo-Signature: sha256=<hex>`, HMAC-SHA256 over the body with the per-subscriber secret. Byte-for-byte parity with [ryo/api/internal/webhook/delivery.go:17-21](ryo/api/internal/webhook/delivery.go:17). Locked by test, not documentation.
- Retry schedule is fixed: first retry at 30s, second at 5min, dead on the third failure. Locked by test. The term "immediate" in §8.2 of the spec refers to the original dispatch, not a retry.
- Ledger ships before events. Do not start both in the same iteration.
- Operational gates before production traffic on either service: Prometheus-compatible `/metrics`, written ADR declaring `webhook_deliveries` is owned by `ryo/events` (others read-only), and (for events) a load test seeding production-volume rows and asserting drainage under a target time.

---

## File Structure

```
ryo/
  ledger/                                # NEW (Kotlin) — phase 1
    src/main/kotlin/com/ryo/ledger/
      reconcile/                         # status mapping + diff logic LIVES IN CODE here
      api/                               # POST /v1/reconciliation/run, GET /v1/reconciliation
      observability/                     # /metrics
    src/test/kotlin/com/ryo/ledger/
      ReconcilerTest.kt                  # pure unit
      StatusMappingTest.kt               # locks the status equivalence table
      ReconciliationRoutesTest.kt        # DB-backed
  events/                                # NEW (Kotlin) — phase 2
    src/main/kotlin/com/ryo/events/
      delivery/                          # signer, http client, retry policy
      pipeline/                          # claim-and-dispatch, worker
      observability/                     # /metrics
    src/test/kotlin/com/ryo/events/
      WebhookSignerParityTest.kt         # byte-parity vs Go
      RetryPolicyTest.kt                 # 30s, 5min, dead
      ClaimAndDispatchRaceTest.kt        # locks the §8.3 fix
      WorkerLoadTest.kt                  # 5000 rows < 60s, configurable
  api/                                   # EXISTING (Go) — small change in phase 2
    cmd/api/main.go                      # env-gate the Go worker
    migrations/
      00012_webhook_deliveries_dispatching.sql  # NEW (enables claim-and-dispatch)
      00013_reconciliation_runs.sql              # NEW
```

---

## Phase 1 — `ryo/ledger`

### Task 1: Scaffold `ryo/ledger` with a `/health` endpoint

**Files:**
- Create: `ryo/ledger/` (build config, source tree, entry point)
- Create: `ryo/ledger/README.md` (one screen: purpose, env vars, ports)

**Interfaces:**
- Produces: a running Kotlin/JVM 21 service on port 8093 that responds `GET /health` → `{"status":"ok"}` with `Content-Type: application/json`. No DB, no Stripe yet.

**Why this is one task:** the implementer picks the stack here (build tool, HTTP framework, test harness) and proves it works end-to-end. Every subsequent task assumes it. Folding "set up build config" into the first feature task would couple the technology choice to a feature decision.

- [ ] **Step 1: Write the failing test**

Create a test that boots the service in-process (or against a dev port) and asserts `GET /health` returns 200 with body `{"status":"ok"}` and JSON content-type.

```kotlin
// pseudocode — implementer chooses test framework + harness
@Test
fun health_returns_ok_json() {
    val resp = httpGet("/health")
    assertEquals(200, resp.status)
    assertEquals("application/json", resp.contentType)
    assertEquals("""{"status":"ok"}""", resp.body)
}
```

- [ ] **Step 2: Run the test and verify it fails**

Expected: build error (no source yet) or test failure (no route).

- [ ] **Step 3: Write the build config + entry point**

Build config must:
- Pin JVM 21 toolchain
- Wire up a JUnit-compatible test runner
- Declare a single executable entry point that reads `PORT` (default `8093`) from env and starts an HTTP server

Entry point installs one route: `GET /health` → `200 {"status":"ok"}`.

- [ ] **Step 4: Run the test and verify it passes**

- [ ] **Step 5: Write the README**

Cover: what the service does (one paragraph), how to run it locally, env vars table (just `PORT` for now), the port. Do not document endpoints that don't exist yet.

- [ ] **Step 6: Commit**

```bash
git add ryo/ledger/
git commit -m "feat(ledger): scaffold kotlin service with health route"
```

---

### Task 2: Add the `reconciliation_runs` migration

**Files:**
- Create: `ryo/api/migrations/00013_reconciliation_runs.sql`

**Interfaces:**
- Produces: table `reconciliation_runs (id TEXT PK, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ NULL, window_start TIMESTAMPTZ, window_end TIMESTAMPTZ, sessions_checked INT, drifts_found INT, status TEXT CHECK ('running'|'ok'|'drift'|'error'), notes JSONB)`. An index on `started_at DESC` so the listing endpoint can paginate cheaply.

**Why migration 00013, not 00012:** 00012 is reserved for the events service's `dispatching` status migration (Phase 2, Task 5). Ledger ships first but events' migration is more impactful, so numbering reflects logical order, not ship order. The numbers are gaps-free; they just don't ship in numeric order.

- [ ] **Step 1: Write the migration**

```sql
-- +goose Up
CREATE TABLE reconciliation_runs (
  id               TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ,
  window_start     TIMESTAMPTZ NOT NULL,
  window_end       TIMESTAMPTZ NOT NULL,
  sessions_checked INT         NOT NULL DEFAULT 0,
  drifts_found     INT         NOT NULL DEFAULT 0,
  status           TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','ok','drift','error')),
  notes            JSONB       NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX reconciliation_runs_started_idx ON reconciliation_runs (started_at DESC);

-- +goose Down
DROP TABLE reconciliation_runs;
```

- [ ] **Step 2: Apply and verify**

Run: `cd ryo/api && go run ./cmd/migrate up`
Expected: migration 00013 applies cleanly.

Run `psql` and `\d reconciliation_runs`. Expected: columns + CHECK constraint + index present.

- [ ] **Step 3: Commit**

```bash
git add ryo/api/migrations/00013_reconciliation_runs.sql
git commit -m "feat(api): reconciliation_runs table (owned by ryo/ledger)"
```

---

### Task 3: Status mapping + pure `Reconciler` diff logic

**Files:**
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/StatusMapping.kt`
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/Reconciler.kt`
- Create: `ryo/ledger/src/test/kotlin/com/ryo/ledger/reconcile/StatusMappingTest.kt`
- Create: `ryo/ledger/src/test/kotlin/com/ryo/ledger/reconcile/ReconcilerTest.kt`

**Interfaces:**
- Produces:
  ```
  data class LocalSession(id: String, piId: String, status: String, amountCents: Long)
  data class StripeView(piId: String, status: String, amountCents: Long)
  data class Drift(sessionId: String, piId: String, localStatus: String, stripeStatus: String, localAmount: Long, stripeAmount: Long)

  object StatusMapping {
      fun equivalent(local: String, stripe: String): MappingResult
  }
  sealed interface MappingResult { object Match; object Mismatch; data class Unmapped(val unknown: String): MappingResult }

  object Reconciler {
      fun diff(local: List<LocalSession>, stripe: List<StripeView>): List<Drift>
  }
  ```
- Sentinel strings in the `Drift`'s `stripeStatus` / `localStatus` fields:
  - `"missing-in-stripe"` — local session has no matching `piId` in Stripe
  - `"missing-locally"` — Stripe `PaymentIntent` has no matching local session
  - `"unmapped-local-status"` — local status not in the equivalence table (see §8.1 resolution below)

**Resolving spec §8.1 (unmapped statuses):** the implementer cannot silently treat an unknown local status as "no match." This plan picks the **fail-loud** path: `StatusMapping.equivalent` returns `Unmapped`, the `Reconciler` records a drift with `localStatus = "unmapped-local-status"` and `stripeStatus = <observed stripe status>`. This makes a missing entry in the mapping table visible immediately the first time a new status appears in production, rather than after a regulator asks why the books look wrong.

- [ ] **Step 1: Write the status mapping test (locks the equivalence table)**

```kotlin
// StatusMappingTest.kt — pseudocode, implementer picks assertion lib
@Test fun completed_matches_succeeded() { assertMatch("completed", "succeeded") }
@Test fun failed_matches_payment_failed() { assertMatch("failed", "payment_failed") }
@Test fun failed_matches_canceled() { assertMatch("failed", "canceled") }
@Test fun pending_matches_requires_payment_method() { assertMatch("pending", "requires_payment_method") }
@Test fun pending_matches_processing() { assertMatch("pending", "processing") }
@Test fun pending_matches_requires_confirmation() { assertMatch("pending", "requires_confirmation") }
@Test fun completed_does_not_match_processing() { assertMismatch("completed", "processing") }
@Test fun unknown_local_returns_unmapped() {
    val r = StatusMapping.equivalent("expired", "succeeded")
    assertEquals(MappingResult.Unmapped("expired"), r)
}
```

The pairs above are derived from every code path in [ryo/api/internal/stripe/handler.go](ryo/api/internal/stripe/handler.go) and [ryo/api/internal/session/handler.go](ryo/api/internal/session/handler.go) — the only local statuses ever written are `pending`, `completed`, `failed`.

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement `StatusMapping`**

A `Map<String, Set<String>>` keyed by local status, plus a default branch that returns `Unmapped`. Keep it data-driven — the equivalence table is the API; no hardcoded `when` branches in callers.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Write the `Reconciler` test**

```kotlin
@Test fun no_drift_when_status_and_amount_match() {
    assertTrue(Reconciler.diff(
        listOf(LocalSession("s1", "pi_1", "completed", 100)),
        listOf(StripeView("pi_1", "succeeded", 100)),
    ).isEmpty())
}

@Test fun amount_mismatch_is_a_drift_even_when_status_matches() {
    val drifts = Reconciler.diff(
        listOf(LocalSession("s1", "pi_1", "completed", 100)),
        listOf(StripeView("pi_1", "succeeded", 200)),
    )
    assertEquals(1, drifts.size)
    assertEquals(100L, drifts[0].localAmount)
    assertEquals(200L, drifts[0].stripeAmount)
}

@Test fun status_mismatch_is_a_drift_even_when_amount_matches() {
    val drifts = Reconciler.diff(
        listOf(LocalSession("s1", "pi_1", "completed", 100)),
        listOf(StripeView("pi_1", "processing", 100)),
    )
    assertEquals(1, drifts.size)
}

@Test fun missing_in_stripe_uses_sentinel() {
    val drifts = Reconciler.diff(listOf(LocalSession("s1", "pi_1", "completed", 100)), emptyList())
    assertEquals(1, drifts.size)
    assertEquals("missing-in-stripe", drifts[0].stripeStatus)
    assertEquals(0L, drifts[0].stripeAmount)
}

@Test fun missing_locally_uses_sentinel() {
    val drifts = Reconciler.diff(emptyList(), listOf(StripeView("pi_1", "succeeded", 100)))
    assertEquals(1, drifts.size)
    assertEquals("missing-locally", drifts[0].localStatus)
    assertEquals("", drifts[0].sessionId)
}

@Test fun unmapped_local_status_uses_sentinel_with_observed_stripe_status() {
    val drifts = Reconciler.diff(
        listOf(LocalSession("s1", "pi_1", "expired", 100)),
        listOf(StripeView("pi_1", "succeeded", 100)),
    )
    assertEquals(1, drifts.size)
    assertEquals("unmapped-local-status", drifts[0].localStatus)
    assertEquals("succeeded", drifts[0].stripeStatus)
}
```

- [ ] **Step 6: Run and verify failure**

- [ ] **Step 7: Implement `Reconciler`**

Pure function. Index local by `piId` once, iterate. For each local: lookup, classify (missing-in-stripe / unmapped / mismatch / match). Then pass over stripe rows to find `missing-locally`. No I/O, no logging.

- [ ] **Step 8: Run and verify pass**

- [ ] **Step 9: Commit**

```bash
git add ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/ ryo/ledger/src/test/kotlin/com/ryo/ledger/reconcile/
git commit -m "feat(ledger): pure reconciler + status mapping table (locked by tests)"
```

---

### Task 4: Wire `POST /v1/reconciliation/run` + `GET /v1/reconciliation`

**Files:**
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/SessionRepository.kt` (reads `sessions` for a window)
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/StripeClient.kt` (lists `PaymentIntent` for a window)
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/reconcile/RunRepository.kt` (writes/reads `reconciliation_runs`)
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/api/ReconciliationRoutes.kt`
- Create: `ryo/ledger/src/test/kotlin/com/ryo/ledger/api/ReconciliationRoutesTest.kt`
- Modify: `ryo/ledger/src/main/kotlin/com/ryo/ledger/Main.kt` — install reconciliation routes alongside `/health`

**Interfaces:**
- `POST /v1/reconciliation/run?from=<iso>&to=<iso>` → 200 with `{id, sessions_checked, drifts_found, status}`. Persists the run synchronously. Bad ISO → 400.
- `GET /v1/reconciliation` → 200 with an array of the 50 most recent runs, newest first.
- `SessionRepository.listInWindow(from, to)` returns local sessions where `started_at IN [from, to)` AND `stripe_payment_intent_id IS NOT NULL`.
- `StripeClient.listInWindow(from, to)` paginates Stripe's `PaymentIntent` list with `created.gte = from` and `created.lt = to`, returning every page concatenated.
- `RunRepository.write(run)` and `RunRepository.recent(limit)` for the listing endpoint.

**Test injection:** the route handler accepts `stripeProvider: suspend (OffsetDateTime, OffsetDateTime) -> List<StripeView>` so tests can substitute a deterministic list without a real Stripe key. The production wiring binds `StripeClient::listInWindow` to that param.

- [ ] **Step 1: Write the failing route test**

Use the existing Postgres test pattern (the Go side uses `TEST_DATABASE_URL`; the Kotlin tests should accept the same env var and skip cleanly when unset, mirroring `ryo/api/internal/session/store_test.go`).

```kotlin
@Test fun run_persists_and_list_returns_it() {
    val factory = pgFactoryFromEnv() ?: return // skip when TEST_DATABASE_URL unset
    applyMigrationsUpTo("00013", factory)
    seedSession(factory, id = "s1", piId = "pi_run_1", status = "completed", amount = 100, startedAt = "2026-06-15T12:00:00Z")
    val fakeStripe = listOf(StripeView("pi_run_1", "succeeded", 100))

    application { wireForTest(factory, stripeProvider = { _, _ -> fakeStripe }) }

    val ran = client.post("/v1/reconciliation/run?from=2026-06-01T00:00:00Z&to=2026-07-01T00:00:00Z")
    assertEquals(200, ran.status)
    val body = ran.bodyAsJson()
    assertEquals(1, body["sessions_checked"])
    assertEquals(0, body["drifts_found"])
    assertEquals("ok", body["status"])

    val list = client.get("/v1/reconciliation")
    assertEquals(200, list.status)
    val runs = list.bodyAsJsonArray()
    assertEquals(1, runs.size)
    assertEquals(body["id"], runs[0]["id"])
}

@Test fun run_records_drift_when_amounts_disagree() {
    // same seed but fakeStripe returns amount 200 — assert status="drift", drifts_found=1
}

@Test fun bad_iso_returns_400() {
    application { wireForTest(...) }
    val resp = client.post("/v1/reconciliation/run?from=garbage&to=also-garbage")
    assertEquals(400, resp.status)
}
```

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement repositories and the route handlers**

`RunRepository.write` does a single INSERT with the computed status. `recent(50)` runs `SELECT ... ORDER BY started_at DESC LIMIT 50`. `SessionRepository.listInWindow` runs the parameterized SELECT. `StripeClient.listInWindow` walks paginated results until `has_more` is false.

The `POST /v1/reconciliation/run` handler:
1. Parse + validate `from`/`to` (400 on parse failure)
2. Concurrently fetch local sessions + Stripe view (independent I/O — no dependency between them)
3. Run `Reconciler.diff`
4. Determine terminal status: `"ok"` if `drifts.isEmpty()`, `"drift"` otherwise. Reserve `"error"` for the case where one of step 2's fetches threw.
5. Write the run row
6. Return the summary

Tests that seed sessions need to know the FK chain — see `ryo/api/internal/session/store_test.go` line 68 (`seedAgent`) for the org + agent seed pattern. Reuse it.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Commit**

```bash
git add ryo/ledger/
git commit -m "feat(ledger): /v1/reconciliation run + list backed by reconciliation_runs"
```

---

### Task 5: Prometheus `/metrics` on ledger

**Files:**
- Create: `ryo/ledger/src/main/kotlin/com/ryo/ledger/observability/Metrics.kt`
- Modify: `ryo/ledger/src/main/kotlin/com/ryo/ledger/api/ReconciliationRoutes.kt` — increment counters
- Modify: `ryo/ledger/src/main/kotlin/com/ryo/ledger/Main.kt` — install `/metrics`

**Interfaces:**
- `GET /metrics` returns Prometheus text-format exposition.
- Required counters:
  - `ryo_ledger_reconciliation_runs_total{status=ok|drift|error}` — incremented at the end of every run
  - `ryo_ledger_drifts_total{type=missing-in-stripe|missing-locally|status-mismatch|amount-mismatch|unmapped-local-status}` — incremented once per Drift
- Required histogram: `ryo_ledger_reconciliation_duration_seconds` — observed once per run

**Why this is a separate task:** the spec lists metrics as a production gate. Bolting it onto Task 4 would couple the observability story to the feature commit and make it easy to skip in a hurry.

- [ ] **Step 1: Write the test**

```kotlin
@Test fun metrics_endpoint_serves_prometheus_text() {
    // boot service, GET /metrics, assert content-type text/plain;version=0.0.4 and body matches /^# HELP /m
}

@Test fun running_a_reconciliation_increments_counter() {
    // boot service with fake stripe, hit /v1/reconciliation/run, then GET /metrics
    // assert ryo_ledger_reconciliation_runs_total{status="ok"} == 1
}

@Test fun a_drift_increments_per_type_counter() {
    // seed local + fake stripe that disagree on amount
    // assert ryo_ledger_drifts_total{type="amount-mismatch"} == 1
}
```

- [ ] **Step 2: Implement**

Wire a Prometheus client library, register the counters + histogram at startup, install the scrape endpoint, increment counters at the right moments in the handlers.

- [ ] **Step 3: Run and verify pass**

- [ ] **Step 4: Commit**

```bash
git add ryo/ledger/
git commit -m "feat(ledger): prometheus metrics endpoint with run + drift counters"
```

---

## Phase 2 — `ryo/events`

**Begin only after Phase 1 is in production and stable for at least one release cycle.** Events carries a parity burden that ledger doesn't; do not split attention.

### Task 6: Capture the Go byte-parity vector

**Files:**
- Create (then delete): `ryo/api/internal/webhook/parity_vector_test.go`
- Update: a fixture file the Kotlin test will read (path TBD by implementer — e.g. `ryo/events/src/test/resources/parity-vector.txt`)

**Interfaces:**
- Produces: a file containing the canonical signature for the exact pair `(payload=`{"event":"payment.completed"}`, secret="mysecret")`. Format: one line, the literal output of `webhook.SignPayload` — i.e. `sha256=<hex>`.

**Why first in phase 2:** the parity test in Task 8 needs a vector captured *from the Go implementation as it ships today*. Capturing it as a separate step keeps the capture audit-able (one commit, one file, one number) and prevents the Kotlin implementer from accidentally "computing" the expected value from their own implementation, which would defeat the test.

- [ ] **Step 1: Write the throwaway Go test**

```go
// ryo/api/internal/webhook/parity_vector_test.go
package webhook_test

import (
    "fmt"
    "os"
    "testing"

    "github.com/enkyuan/alloy/ryo/api/internal/webhook"
)

func TestCaptureParityVector(t *testing.T) {
    sig := webhook.SignPayload([]byte(`{"event":"payment.completed"}`), "mysecret")
    fmt.Println("PARITY_VECTOR:", sig)
    // Optional: write to fixture path if PARITY_FIXTURE_PATH env is set
    if path := os.Getenv("PARITY_FIXTURE_PATH"); path != "" {
        if err := os.WriteFile(path, []byte(sig+"\n"), 0644); err != nil {
            t.Fatal(err)
        }
    }
}
```

- [ ] **Step 2: Run it and capture the output**

```bash
cd ryo/api
PARITY_FIXTURE_PATH=../events/src/test/resources/parity-vector.txt \
  go test -v -run TestCaptureParityVector ./internal/webhook/
```

- [ ] **Step 3: Verify the fixture**

The fixture must contain exactly one line: `sha256=<64 hex chars>`. Anything else is a capture error.

- [ ] **Step 4: Delete the throwaway test**

```bash
rm ryo/api/internal/webhook/parity_vector_test.go
```

- [ ] **Step 5: Commit**

```bash
git add ryo/events/src/test/resources/parity-vector.txt
git commit -m "test(events): capture webhook signer parity vector from go impl"
```

---

### Task 7: Scaffold `ryo/events` with `/health`

**Files:**
- Create: `ryo/events/` (build config, source tree, entry point on port 8092, `/health` route, README)

**Interfaces:**
- Same shape as Task 1, different port. Reuse whatever stack the implementer picked for ledger.

**Why we don't fold this into Task 8:** same reasoning as Task 1. Stack-validation and feature-implementation are different decisions.

- [ ] **Step 1: Test for `/health`** (same shape as Task 1 Step 1, different port)
- [ ] **Step 2: Run and verify failure**
- [ ] **Step 3: Build config + entry point reading `PORT` (default 8092)**
- [ ] **Step 4: Run and verify pass**
- [ ] **Step 5: README**
- [ ] **Step 6: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): scaffold kotlin service with health route"
```

---

### Task 8: `WebhookSigner` with byte-parity test

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/delivery/WebhookSigner.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/delivery/WebhookSignerParityTest.kt`

**Interfaces:**
- Produces: `object WebhookSigner { fun sign(payload: ByteArray, secret: String): String }` returning `"sha256=<lowercase hex>"` byte-identical to the Go implementation.

- [ ] **Step 1: Write the parity test reading the fixture**

```kotlin
@Test
fun matches_go_captured_vector() {
    val expected = readResource("/parity-vector.txt").trim()
    val actual = WebhookSigner.sign(
        """{"event":"payment.completed"}""".toByteArray(Charsets.UTF_8),
        "mysecret",
    )
    assertEquals(expected, actual)
}

@Test
fun deterministic() {
    val a = WebhookSigner.sign("hi".toByteArray(), "s")
    val b = WebhookSigner.sign("hi".toByteArray(), "s")
    assertEquals(a, b)
}

@Test
fun different_secret_produces_different_signature() {
    val a = WebhookSigner.sign("payload".toByteArray(), "s1")
    val b = WebhookSigner.sign("payload".toByteArray(), "s2")
    assertNotEquals(a, b)
}
```

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement using `javax.crypto.Mac` with `HmacSHA256`**

Output format: literal `"sha256="` + lowercase hex of the MAC bytes. Hex encoding details matter — the Go side uses `encoding/hex.EncodeToString` which is lowercase, no separator, no leading `0x`. Match it exactly.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): webhook signer with byte-parity locked by fixture"
```

---

### Task 9: `RetryPolicy` matching the Go schedule

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/delivery/RetryPolicy.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/delivery/RetryPolicyTest.kt`

**Interfaces:**
- Produces:
  ```
  sealed interface RetryDecision {
      data class Retry(val delay: Duration) : RetryDecision   // newStatus is always "failed"
      data object Dead : RetryDecision
  }
  object RetryPolicy {
      // attemptsBefore is the count of failed attempts that have already happened.
      // 0 = "we just had our first failure, schedule the first retry"
      // 1 = "second failure, schedule the second retry"
      // 2+ = dead
      fun next(attemptsBefore: Int): RetryDecision
  }
  ```
- Mirrors [ryo/api/internal/webhook/store.go:180-200](ryo/api/internal/webhook/store.go:180).
- **Spec §8.2 clarification, encoded in a code comment on `RetryPolicy.next`:** the schedule is first-retry-at-30s, second-retry-at-5min, dead-on-third-failure. The original dispatch isn't a retry.

- [ ] **Step 1: Test**

```kotlin
@Test fun first_failure_schedules_30s() {
    val r = RetryPolicy.next(attemptsBefore = 0) as RetryDecision.Retry
    assertEquals(30.seconds, r.delay)
}
@Test fun second_failure_schedules_5min() {
    val r = RetryPolicy.next(attemptsBefore = 1) as RetryDecision.Retry
    assertEquals(5.minutes, r.delay)
}
@Test fun third_failure_is_dead() {
    assertEquals(RetryDecision.Dead, RetryPolicy.next(attemptsBefore = 2))
    assertEquals(RetryDecision.Dead, RetryPolicy.next(attemptsBefore = 99))
}
```

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement**

Use a `when` on `attemptsBefore`. Add a code comment explicitly stating the §8.2 terminology resolution so a future reader doesn't re-introduce the "immediate-30s-5min" framing.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): retry policy (first retry 30s, second 5min, dead on third)"
```

---

### Task 10: Schema migration enabling `dispatching` status — resolves §8.3

**Files:**
- Create: `ryo/api/migrations/00012_webhook_deliveries_dispatching.sql`

**Interfaces:**
- Produces: the `webhook_deliveries.status` CHECK constraint now permits `'dispatching'` in addition to the existing values. Existing rows are not touched.

**Why this matters — §8.3 in concrete terms:** today's Go worker reads with `FOR UPDATE SKIP LOCKED`, then **releases the row lock when the read transaction closes** (which happens as soon as the read loop in `PollPending` finishes), and **then** launches goroutines that perform their own writes on fresh connections. The lock doesn't protect the dispatch-and-update window. Once two workers run simultaneously, a row whose lock window happened to close before the second worker polled can be picked up twice.

The fix is to **claim-then-dispatch**: in one statement, atomically flip eligible rows from `pending` to `dispatching` and return them. Only then dispatch. On terminal write (delivered / failed / dead), the row leaves `dispatching` and goes to its final state. Both workers can use this pattern; the schema must permit the intermediate status before either worker can adopt it.

Important: this migration is non-breaking. It expands the CHECK; existing rows keep their status. The Go worker keeps working unchanged (it doesn't write `dispatching`). When the Kotlin worker ships in Task 12 using the new pattern, the Go worker can continue running as-is — no row will be claimed by both because the Kotlin worker's CTE write happens atomically.

- [ ] **Step 1: Write the migration**

```sql
-- +goose Up
ALTER TABLE webhook_deliveries
  DROP CONSTRAINT webhook_deliveries_status_check;

ALTER TABLE webhook_deliveries
  ADD CONSTRAINT webhook_deliveries_status_check
  CHECK (status IN ('pending', 'dispatching', 'delivered', 'failed', 'dead'));

-- +goose Down
ALTER TABLE webhook_deliveries
  DROP CONSTRAINT webhook_deliveries_status_check;

-- WARNING: reverting will fail if any rows are currently in 'dispatching'.
-- Drain via the kotlin worker before rolling back.
ALTER TABLE webhook_deliveries
  ADD CONSTRAINT webhook_deliveries_status_check
  CHECK (status IN ('pending', 'delivered', 'failed', 'dead'));
```

The Down migration's drain warning is real — leaving it in the SQL header (not just an external doc) ensures whoever runs the rollback sees it.

- [ ] **Step 2: Apply and verify**

```bash
cd ryo/api && go run ./cmd/migrate up
psql ... -c "\d webhook_deliveries" | grep status_check
```

Expected: CHECK clause includes `dispatching`.

- [ ] **Step 3: Commit**

```bash
git add ryo/api/migrations/00012_webhook_deliveries_dispatching.sql
git commit -m "feat(api): allow 'dispatching' status on webhook_deliveries (enables claim-and-dispatch)"
```

---

### Task 11: Claim-and-dispatch repository + race test

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/pipeline/DeliveryRow.kt`
- Create: `ryo/events/src/main/kotlin/com/ryo/events/pipeline/DeliveryRepository.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/pipeline/DeliveryRepositoryTest.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/pipeline/ClaimAndDispatchRaceTest.kt`

**Interfaces:**
- `data class DeliveryRow(id, webhookId, eventType, payload: ByteArray, attempts: Int, webhookUrl, webhookSecret)`
- `class DeliveryRepository`:
  - `suspend fun claim(limit: Int): List<DeliveryRow>` — atomically flips up to `limit` rows from `pending` to `dispatching` AND returns them with `webhooks.url` + `webhooks.secret` joined in. Single statement, CTE-based:
    ```sql
    WITH claimed AS (
      SELECT id FROM webhook_deliveries
      WHERE status = 'pending' AND next_attempt <= now()
      ORDER BY next_attempt
      LIMIT $1
      FOR UPDATE SKIP LOCKED
    )
    UPDATE webhook_deliveries d
    SET status = 'dispatching'
    FROM claimed c
    WHERE d.id = c.id
    RETURNING d.id, d.webhook_id, d.event_type, d.payload, d.attempts,
              (SELECT url FROM webhooks WHERE id = d.webhook_id),
              (SELECT secret FROM webhooks WHERE id = d.webhook_id);
    ```
  - `suspend fun markDelivered(id: String, httpStatus: Int)` — sets status to `'delivered'`
  - `suspend fun markFailed(id: String, httpStatus: Int?, attemptsBefore: Int, decision: RetryDecision)` — bumps `attempts = attemptsBefore + 1`, sets `next_attempt` from the decision, status `'failed'` or `'dead'`. Single UPDATE statement so the attempt count and the status flip together.

**Resolving spec §8.3 in tests, not docs:** `ClaimAndDispatchRaceTest` runs two repositories concurrently against the same DB and asserts that no row appears in both result sets. This locks the fix.

- [ ] **Step 1: Race test (write it first — it's the whole point)**

```kotlin
@Test fun two_concurrent_claims_never_return_the_same_row() {
    val factory = pgFactoryFromEnv() ?: return
    applyMigrationsUpTo("00012", factory)
    seedWebhook(factory, id = "wh-1", url = "https://e.test", secret = "s")
    repeat(100) { seedDelivery(factory, id = "d-$it", webhookId = "wh-1", payload = """{"i":$it}""") }

    val repoA = DeliveryRepository(factory)
    val repoB = DeliveryRepository(factory)

    val results = runBlocking {
        // Fire both claims as concurrently as possible
        listOf(
            async { repoA.claim(limit = 50) },
            async { repoB.claim(limit = 50) },
        ).awaitAll()
    }

    val idsA = results[0].map { it.id }.toSet()
    val idsB = results[1].map { it.id }.toSet()
    val overlap = idsA intersect idsB
    assertTrue(overlap.isEmpty(),
        "race detected: ${overlap.size} rows claimed by both workers: $overlap")
    assertEquals(100, idsA.size + idsB.size, "total claimed != 100 (lost rows)")

    // Every claimed row must be in 'dispatching' state, none still 'pending'
    assertEquals(0, countByStatus(factory, "pending"))
    assertEquals(100, countByStatus(factory, "dispatching"))
}
```

- [ ] **Step 2: `DeliveryRepository` unit tests**

```kotlin
@Test fun claim_skips_rows_not_yet_due() {
    seedDelivery(factory, id = "future", nextAttempt = now().plusMinutes(5))
    val claimed = repo.claim(limit = 10)
    assertTrue(claimed.none { it.id == "future" })
}

@Test fun mark_delivered_moves_row_out_of_dispatching() {
    val claimed = repo.claim(limit = 1).single()
    repo.markDelivered(claimed.id, httpStatus = 200)
    assertEquals("delivered", statusOf(factory, claimed.id))
}

@Test fun mark_failed_first_attempt_writes_failed_with_30s_next_attempt() {
    val claimed = repo.claim(limit = 1).single()
    val before = now()
    repo.markFailed(claimed.id, httpStatus = 500, attemptsBefore = 0,
        decision = RetryDecision.Retry(30.seconds))
    val (status, attempts, next) = rowOf(factory, claimed.id)
    assertEquals("failed", status)
    assertEquals(1, attempts)
    assertTrue(next >= before.plusSeconds(29) && next <= before.plusSeconds(31))
}

@Test fun mark_failed_dead_writes_dead_status() {
    val claimed = repo.claim(limit = 1).single()
    repo.markFailed(claimed.id, httpStatus = 500, attemptsBefore = 2,
        decision = RetryDecision.Dead)
    assertEquals("dead", statusOf(factory, claimed.id))
}
```

- [ ] **Step 3: Run and verify failure**

- [ ] **Step 4: Implement `DeliveryRepository`**

`claim` runs the CTE above as a single statement. `markDelivered` and `markFailed` each run one statement. All three open and close their own connection; no shared session state.

- [ ] **Step 5: Run all tests and verify pass — including the race test**

- [ ] **Step 6: Commit**

```bash
git add ryo/events/src/main/kotlin/com/ryo/events/pipeline/ \
        ryo/events/src/test/kotlin/com/ryo/events/pipeline/
git commit -m "feat(events): claim-and-dispatch repository (closes §8.3 race)"
```

---

### Task 12: `DeliveryClient` (signed POST)

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/delivery/DeliveryClient.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/delivery/DeliveryClientTest.kt`

**Interfaces:**
- `class DeliveryClient`:
  - `suspend fun deliver(url: String, secret: String, payload: ByteArray): Int` — POSTs `payload` with `Content-Type: application/json` and `X-Ryo-Signature: <WebhookSigner.sign(...)>`. Returns the HTTP status code. **Does not throw** on non-2xx — non-2xx is a normal return path that the worker uses to drive retry. **Throws** on transport errors (DNS, timeout, connection reset) — the worker catches those.
  - 10-second total request timeout, matching [delivery.go:35](ryo/api/internal/webhook/delivery.go:35).

- [ ] **Step 1: Test**

```kotlin
@Test fun deliver_sets_signature_header_and_returns_status() {
    var capturedSig: String? = null
    val client = DeliveryClient(httpClientFor { req ->
        capturedSig = req.headers["X-Ryo-Signature"]
        respond(status = 200, body = "")
    })
    val status = runBlocking { client.deliver("https://e.test/hook", "secret", """{"a":1}""".toByteArray()) }
    assertEquals(200, status)
    assertNotNull(capturedSig)
    assertTrue(capturedSig!!.startsWith("sha256="))
}

@Test fun deliver_returns_non_2xx_without_throwing() {
    val client = DeliveryClient(httpClientFor { respond(status = 500, body = "") })
    assertEquals(500, runBlocking { client.deliver("https://e.test/hook", "secret", "{}".toByteArray()) })
}

@Test fun deliver_throws_on_transport_error() {
    val client = DeliveryClient(httpClientFor { throw IOException("connection refused") })
    assertThrows<IOException> {
        runBlocking { client.deliver("https://nope.test/hook", "secret", "{}".toByteArray()) }
    }
}
```

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement**

Take an HTTP client by constructor injection so tests can substitute. In production, configure the real client with a 10s total timeout.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): delivery client with signed POST and status return"
```

---

### Task 13: `Worker` (bounded concurrency + jittered retry)

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/pipeline/Worker.kt`
- Create: `ryo/events/src/test/kotlin/com/ryo/events/pipeline/WorkerTest.kt`
- Modify: `ryo/events/src/main/kotlin/com/ryo/events/Main.kt` — start the worker

**Interfaces:**
- `class Worker(repo, client, maxConcurrent: Int, pollInterval: Duration)`
- `fun run(scope): Job` — launches a long-running loop:
  1. `claim(limit = maxConcurrent * 4)` (over-claim a small batch to keep the pipeline saturated under bursty delivery)
  2. For each claimed row, dispatch under a `Semaphore(maxConcurrent)`
  3. Per row: call `client.deliver`; on 2xx, `markDelivered`; on non-2xx, `markFailed` with `RetryPolicy.next(row.attempts)`, applying ±10% jitter to any `Retry.delay`; on transport throw, `markFailed` with no httpStatus
  4. Sleep `pollInterval` between cycles
- Cancelling the scope stops the loop cleanly. Anything in-flight finishes; no new rows are claimed.

**Improvements over the Go worker, per §4.4:**
- Bounded concurrency via `Semaphore(maxConcurrent)` (Go uses unbounded `go dispatchOne`)
- ±10% multiplicative jitter on retry delays (Go uses fixed 30s / 5min)

- [ ] **Step 1: Test**

```kotlin
@Test fun worker_delivers_seeded_rows_and_marks_them_delivered() {
    val factory = pgFactoryFromEnv() ?: return
    applyMigrationsUpTo("00012", factory)
    seedWebhook(factory, id = "wh-1", url = "https://e.test/hook", secret = "s")
    repeat(20) { seedDelivery(factory, id = "d-$it", webhookId = "wh-1") }

    val sent = AtomicInteger(0)
    val client = DeliveryClient(httpClientFor {
        sent.incrementAndGet()
        respond(200, "")
    })
    val worker = Worker(
        repo = DeliveryRepository(factory),
        client = client,
        maxConcurrent = 4,
        pollInterval = 50.milliseconds,
    )

    runBlocking {
        val job = worker.run(this)
        delay(1.seconds)  // a handful of cycles
        job.cancelAndJoin()
    }

    assertEquals(20, sent.get())
    assertEquals(20, countByStatus(factory, "delivered"))
    assertEquals(0, countByStatus(factory, "pending"))
    assertEquals(0, countByStatus(factory, "dispatching"))
}

@Test fun worker_records_failure_and_schedules_retry_with_jitter() {
    seedWebhook(factory, id = "wh-1", url = "https://e.test/hook", secret = "s")
    seedDelivery(factory, id = "d-1", webhookId = "wh-1")
    val client = DeliveryClient(httpClientFor { respond(500, "") })

    runBlocking {
        val w = Worker(DeliveryRepository(factory), client, 4, 50.milliseconds)
        val j = w.run(this); delay(300.milliseconds); j.cancelAndJoin()
    }

    val (status, attempts, nextAttempt) = rowOf(factory, "d-1")
    assertEquals("failed", status)
    assertEquals(1, attempts)
    // jitter ±10% → next attempt should be in [27s, 33s] from now
    val now = OffsetDateTime.now()
    assertTrue(nextAttempt.isAfter(now.plusSeconds(27)))
    assertTrue(nextAttempt.isBefore(now.plusSeconds(34)))
}

@Test fun worker_bounds_concurrent_dispatch() {
    // Use a client whose handler counts current in-flight requests
    // and records the max observed. Assert observed max <= maxConcurrent.
}
```

- [ ] **Step 2: Run and verify failure**

- [ ] **Step 3: Implement**

Pseudocode:
```kotlin
fun run(scope: CoroutineScope): Job {
    val gate = Semaphore(maxConcurrent)
    return scope.launch {
        while (isActive) {
            val rows = repo.claim(maxConcurrent * 4)
            for (row in rows) {
                launch {
                    gate.withPermit { dispatch(row) }
                }
            }
            delay(pollInterval)
        }
    }
}

private suspend fun dispatch(row: DeliveryRow) {
    val status: Int? = try { client.deliver(row.webhookUrl, row.webhookSecret, row.payload) }
                       catch (t: Throwable) { null }
    when {
        status == null -> repo.markFailed(row.id, null, row.attempts, jitter(RetryPolicy.next(row.attempts)))
        status in 200..299 -> repo.markDelivered(row.id, status)
        else -> repo.markFailed(row.id, status, row.attempts, jitter(RetryPolicy.next(row.attempts)))
    }
}

private fun jitter(d: RetryDecision): RetryDecision = when (d) {
    is RetryDecision.Retry -> {
        val factor = 0.9 + Random.nextDouble() * 0.2  // [0.9, 1.1)
        d.copy(delay = d.delay * factor)
    }
    RetryDecision.Dead -> d
}
```

`Main.kt`: read `DATABASE_URL`, `EVENTS_MAX_CONCURRENT` (default 16), `EVENTS_POLL_INTERVAL_MS` (default 500), construct the worker, launch in the application's coroutine scope, cancel on shutdown signal.

- [ ] **Step 4: Run and verify pass**

- [ ] **Step 5: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): bounded-concurrency worker with jittered retry"
```

---

### Task 14: Prometheus `/metrics` on events

**Files:**
- Create: `ryo/events/src/main/kotlin/com/ryo/events/observability/Metrics.kt`
- Modify: `ryo/events/src/main/kotlin/com/ryo/events/pipeline/Worker.kt` — increment counters
- Modify: `ryo/events/src/main/kotlin/com/ryo/events/Main.kt` — install `/metrics`

**Interfaces:**
- `GET /metrics` returns Prometheus text-format exposition.
- Required counters:
  - `ryo_events_deliveries_total{outcome=delivered|failed|dead|transport_error}` — one increment per dispatch
- Required histogram: `ryo_events_dispatch_duration_seconds` — observed per dispatch
- Required gauge: `ryo_events_inflight` — current count of in-flight dispatches (incremented entering the semaphore permit, decremented leaving)

- [ ] **Step 1: Test** (same shape as Task 5: hit `/metrics`, run a worker cycle, assert expected counters incremented)

- [ ] **Step 2: Implement**

- [ ] **Step 3: Run and verify pass**

- [ ] **Step 4: Commit**

```bash
git add ryo/events/
git commit -m "feat(events): prometheus metrics (deliveries, dispatch duration, inflight)"
```

---

### Task 15: Load test — gates the cutover

**Files:**
- Create: `ryo/events/src/test/kotlin/com/ryo/events/pipeline/WorkerLoadTest.kt`

**Interfaces:**
- Seeds N rows (default 5000, configurable via `EVENTS_LOAD_TEST_ROWS` env var), runs the worker against a mock HTTP client that responds 200 immediately, asserts:
  1. all N rows reach `delivered` status
  2. total wall-clock time under a configurable target (default 60s on the CI runner; spec §5.2 calls this a "target time" — the implementer picks a value defensible for the expected production volume and the CI environment)
- Tagged so it can be skipped in fast CI loops and run in the pre-cutover check.

- [ ] **Step 1: Write the test**

```kotlin
@Tag("load")
@Test
fun drains_target_volume_within_target_time() {
    val rows = (System.getenv("EVENTS_LOAD_TEST_ROWS") ?: "5000").toInt()
    val targetSeconds = (System.getenv("EVENTS_LOAD_TEST_TARGET_S") ?: "60").toLong()
    val factory = pgFactoryFromEnv() ?: return
    applyMigrationsUpTo("00012", factory)
    seedWebhook(factory, "wh-1", url = "https://e.test/hook", secret = "s")
    repeat(rows) { seedDelivery(factory, id = "load-$it", webhookId = "wh-1") }

    val client = DeliveryClient(httpClientFor { respond(200, "") })
    val worker = Worker(DeliveryRepository(factory), client, maxConcurrent = 32, pollInterval = 100.milliseconds)
    val elapsed = measureTime {
        runBlocking {
            val j = worker.run(this)
            while (countByStatus(factory, "delivered") < rows) {
                delay(100.milliseconds)
            }
            j.cancelAndJoin()
        }
    }
    assertTrue(elapsed.inWholeSeconds < targetSeconds,
        "drainage took ${elapsed.inWholeSeconds}s, target ${targetSeconds}s for $rows rows")
}
```

- [ ] **Step 2: Run with default sizing**

If it doesn't pass, the implementer tunes `maxConcurrent` and `pollInterval` — adjusting the production defaults — until it does. Don't relax the assertion to make the test pass; relax the production defaults' assumptions to be reachable, then re-tune.

- [ ] **Step 3: Commit**

```bash
git add ryo/events/src/test/kotlin/com/ryo/events/pipeline/WorkerLoadTest.kt
git commit -m "test(events): load test gating cutover (default 5000 rows < 60s)"
```

---

### Task 16: Architecture decision record + cutover runbook

**Files:**
- Create: `ryo/events/docs/adr-001-webhook-deliveries-ownership.md`
- Create: `ryo/events/docs/cutover-runbook.md`
- Modify: `ryo/api/cmd/api/main.go` — env-gate the Go worker on `WEBHOOK_WORKER_ENABLED` (default `true`)

**Interfaces:**
- ADR-001 declares the §5.4 fact: **`webhook_deliveries` is owned by `ryo/events`. Other services read-only.** Include the date and the rationale (a single owner avoids the contention pattern from spawning a third consumer down the line).
- The cutover runbook covers §4.5 with an owner and target date that the implementer fills in at the time of writing — placeholders are not acceptable in the final committed file:

  > **Owner:** _[engineer's name]_
  > **Target date for Go worker removal:** _[YYYY-MM-DD]_
  >
  > 1. Deploy `ryo/events` with the env vars from its README. Both workers run.
  > 2. Watch `ryo_events_deliveries_total` and the Go worker's `slog` output for one week. Per-status counts must agree to within transport-error variance.
  > 3. Flip `WEBHOOK_WORKER_ENABLED=false` on `ryo/api`. Only Kotlin runs.
  > 4. After one full release with the flag off, delete the Go worker code (the `Worker`, `runBatch`, `dispatchOne` functions in `ryo/api/internal/webhook/delivery.go`) and revisit migration 00012's Down clause.

- [ ] **Step 1: Write the ADR**

Short — title, status (Accepted), date, context, decision, consequences. The consequence section names what changes if someone violates the rule (e.g., "any other service writing to `webhook_deliveries` will likely race with the worker's claim statement").

- [ ] **Step 2: Write the cutover runbook**

Must have a real owner and a real date. CI will fail on `_[engineer's name]_` left in the file (regex check in the next step or in the commit hook the implementer can add).

- [ ] **Step 3: Add the env gate to the Go side**

```go
// ryo/api/cmd/api/main.go, replacing the existing lines 50-52
if envOr("WEBHOOK_WORKER_ENABLED", "true") == "true" {
    whStore := webhookhandler.NewStore(s.DB)
    go webhookhandler.Worker(ctx, whStore, 2*time.Second)
}
```

- [ ] **Step 4: Sanity check**

```bash
cd ryo/api && go build ./... && go vet ./...
```

Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add ryo/events/docs/ ryo/api/cmd/api/main.go
git commit -m "feat(events): adr + cutover runbook; gate go worker on WEBHOOK_WORKER_ENABLED"
```

---

## Self-Review

**Spec coverage check (every numbered section of the input doc):**

| Spec section | Where covered |
| --- | --- |
| §1 background, alloy#32 fixes | Header note, no task needed |
| §2 architecture (3 services, shared DB) | File Structure + Global Constraints |
| §3.1-§3.3 ledger purpose, flow, drift definition | Task 3 (Reconciler) |
| §3.4 endpoints | Task 4 |
| §3.5 data model | Task 2 |
| §4.1-§4.2 events purpose, flow | Tasks 11, 13 |
| §4.3 parity (signature + retry) | Tasks 6, 8, 9 — locked by tests |
| §4.4 improvements (bounded concurrency + jitter) | Task 13 |
| §4.5 coexistence + cutover | Tasks 10, 16 |
| §5.1 metrics | Tasks 5, 14 |
| §5.2 load test | Task 15 |
| §5.3 status mapping in code | Task 3 (`StatusMapping.kt` beside `Reconciler.kt`) |
| §5.4 ownership ADR | Task 16 |
| §6 sequencing (ledger first) | Phase 1 → Phase 2 split |
| §7 out of scope | Global Constraints + "What's NOT in scope" below |
| §8.1 unmapped status risk | Task 3 — encoded as `MappingResult.Unmapped` returning a `"unmapped-local-status"` drift |
| §8.2 retry terminology | Task 9 — code comment + test naming |
| §8.3 dual-running race | Tasks 10, 11 — schema + claim-and-dispatch, locked by `ClaimAndDispatchRaceTest` |

**Placeholder scan:** none. Every code block is real (pseudocode flagged where the implementer picks the stack). Every test step has an assertion target. The cutover runbook owner/date placeholder is the *only* unfilled value, and the plan flags it explicitly — Task 16 step 2 says CI must fail on it.

**Type consistency:** `RetryPolicy.next(attemptsBefore: Int)` returns `RetryDecision`. `DeliveryRow.attempts: Int`. `Worker.dispatch` passes `row.attempts` straight to `RetryPolicy.next`. `LocalSession.amountCents: Long` matches `StripeView.amountCents: Long`. `Drift.localStatus` / `stripeStatus` are `String` because they carry sentinel values (`"missing-in-stripe"`, `"missing-locally"`, `"unmapped-local-status"`) alongside real statuses; not an enum.

## What's NOT in scope

- Any rewrite of `ryo/api`, `ryo/consumer`, or `ryo/auth`
- Any non-Kotlin JVM language
- Kaji-dependent functionality (agent runtime, tool execution, conversation events)
- GraalVM / ahead-of-time native compilation
- Replacing Postgres with a pub/sub backplane

## GSTACK REVIEW REPORT

_(populated by /plan-eng-review and /plan-ceo-review)_

NO UNRESOLVED DECISIONS

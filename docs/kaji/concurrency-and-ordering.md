# Concurrency and Ordering

## Turn coordination

Turns for the same session serialize FIFO. Turns for different sessions may
run concurrently. The default coordinator is shared by runtimes that use the
same event-store object, but it is process-local. Separate processes do not
coordinate unless the application injects a distributed `TurnCoordinator` or
`SessionTurnCoordinator`.

Cancellation while waiting for the session lease removes the waiter. A
cancelled waiter must not block later turns.

## Event ordering

Persisted events have a contiguous, session-local `sequence`. Read, replay, and
subscription order is sequence order, never timestamp order. Timestamps remain
observability data and may be equal or move backward.

New writes use `NewKajiEvent` and become `StoredKajiEvent` only after the
journal assigns a sequence. Every runtime event from a turn carries the same
non-empty turn ID. Use `(session_id, sequence)` as the durable cursor and
`turn_id` for correlation.

The in-memory event store owns one non-nesting commit lane per session. Direct
store calls and every journal/committer over the same store share that lane, so
sequence allocation, ID reservation, append, subscription attachment, and
fanout are atomic for one session without a process-global event lock.
Cross-session order is deliberately unspecified. Lanes are released only when
their holder and waiter counts both reach zero.

## Whole-turn deadlines and quarantine

One effective work deadline covers the session queue, provider open/stream,
approval, and tools. The configured default is 120 seconds; an earlier caller
deadline may tighten it. Caller return is bounded by that work deadline plus a
5-second cancellation grace for cooperative provider shutdown.

If a provider ignores cancellation beyond the grace period, Kaji records
`PROVIDER_CANCELLATION_CONTRACT_VIOLATION` and leaves that session quarantined
behind the still-owned lease. Call `drain_providers()` or `drainProviders()`
before another turn. Closing rejects new work but cannot force-kill hostile
in-process code; restart the process if the operation never settles.

## Explicit session purge

Session purge is explicit and session-scoped; `close()` never deletes history.
The runtime rejects purge while that session has queued or active turn work,
projection work, tool settlement, or provider quarantine. Drain owned work,
purge the named session, and only then close the runtime:

```ts
await runtime.drainTools(graceMs);
await runtime.drainProviders(graceMs);
await runtime.purgeSession(sessionId);
runtime.close();
```

Before this sequence, stop ingress for the named session. Otherwise another
caller can start work between drain and purge; purge fails closed with
`SessionPurgeBusyError`, but deterministic teardown requires the host to fence
ingress and retry. For whole-runtime shutdown, `close()` may run first to block
future turn APIs because history, drain, and purge remain callable. `close()`
does not cancel already-active work. For one session on a live runtime, do not
close the runtime solely to dispose that session.

Custom event stores remain compatible with `EventStore`; opt into deletion by
implementing `PurgeableEventStore`. `supportsSessionPurge(store)` checks that
capability before any runtime cache is cleared. Every live runtime sharing that
store is invalidated for the named session, including its projector,
diagnostics, and settled tool-idempotency entries. Runtime registrations are
weakly held, so discarded runtimes do not become a store-lifetime leak. A new
runtime cannot attach to the store while any session purge fence is active.

Existing custom `ToolIdempotencyLedger` implementations remain source
compatible. To opt into session purge, implement the optional
`releaseSettled(sessionId)` operation so completed and unknown entries are
removed while running entries remain owned. A runtime backed by a legacy custom
ledger rejects purge with `SessionPurgeUnsupportedError` before deleting store
or cache state. After capability and busy preflight, the event store is deleted
first and SDK-owned caches are cleared synchronously before host ledger cleanup
is awaited. If that host cleanup fails, purge rejects but cannot roll back the
already-deleted event history; retry the named purge after repairing the
ledger. Purge deterministically removes SDK-owned indexes and caches, but does
not claim VM string zeroization or deletion of copies already emitted to
providers, logs, sinks, custom stores, crash dumps, or caller-owned objects.

## Bounded replay and context

A cold runtime pages the retained store once. A warm runtime reads only the
suffix after its projector cursor. Provider context keeps complete turns only:
at most 32 turns and 100,000 characters by default. It never slices through a
pending tool
request/result group. If the current turn alone exceeds the character bound,
the runtime raises `ContextWindowOverflowError` instead of sending partial
context.

History is cursor-paged and defaults to 1,024 events. Apply the privileged
journal warning in the package README before reading it: pages can contain
prompts, provider text, tool arguments, tool results, and metadata and are not
redaction-safe.

```python
page = await runtime.history("session", after_sequence=cursor, limit=128)
cursor = page[-1].sequence if page else cursor
```

```ts
for (;;) {
  const page = await runtime.history("session", { afterSequence: cursor, limit: 128 });
  if (page.length === 0) break;
  const next = page.at(-1)!.sequence;
  if (next <= cursor) throw new Error("history cursor did not advance");
  cursor = next;
}
```

The cursor is exclusive: a cursor of 2 starts the next page at sequence 3.
Continue until the explicit empty page; do not infer completion from a short
page. Reusing a session ID after explicit purge starts again at sequence 1, so
reset the cursor to `0` after purge. Default storage and coordination are
process-local; cross-process correctness belongs to any host-supplied
implementation.

## Subscriber overflow

Subscriber queues hold 1,024 events by default. Overflow terminates only the
lagging subscriber with `EventBufferOverflowError` and reports its last and
latest sequence. The agent turn continues. Resume through the journal from the
reported cursor; do not restart the turn or infer a timestamp boundary.

## Historical logs

Stable replay accepts only stored, sequenced events. Migrate unsequenced logs
offline by assigning contiguous sequence values in a documented source order.
Mixed sequenced and unsequenced logs are rejected; the runtime never infers
timestamp ordering.

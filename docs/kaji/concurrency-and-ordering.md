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

## Bounded replay and context

A cold runtime pages the retained store once. A warm runtime reads only the
suffix after its projector cursor. Provider context keeps complete turns only:
at most 32 turns and 100,000 characters by default. It never slices through a
pending tool
request/result group. If the current turn alone exceeds the character bound,
the runtime raises `ContextWindowOverflowError` instead of sending partial
context.

History is cursor-paged and defaults to 1,024 events:

```python
page = await runtime.history("session", after_sequence=cursor, limit=128)
cursor = page[-1].sequence if page else cursor
```

```ts
const page = await runtime.history("session", { afterSequence: cursor, limit: 128 });
cursor = page.at(-1)?.sequence ?? cursor;
```

## Subscriber overflow

Subscriber queues hold 1,024 events by default. Overflow terminates only the
lagging subscriber with `EventBufferOverflowError` and reports its last and
latest sequence. The agent turn continues. Resume through the journal from the
reported cursor; do not restart the turn or infer a timestamp boundary.

## Legacy logs

Stable replay accepts only stored, sequenced events. Fully unsequenced legacy
logs must use `replay_legacy_session()` or `replayLegacySession()`. That named
compatibility path warns and orders by stable `(timestamp, input index)`.
Mixed sequenced and unsequenced logs are rejected. Migrate offline by assigning
contiguous sequence values in the legacy compatibility order while preserving
the original timestamps.
